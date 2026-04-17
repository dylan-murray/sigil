import asyncio
import copy
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from string import Template
from typing import Any

from sigil.core.llm import (
    DOOM_LOOP_MAX_REPEATS,
    ContextOverflowError,
    acompletion,
    context_pressure,
    detect_doom_loop,
    record_tool_call,
    record_tool_result,
    reduce_context,
    safe_max_tokens,
    supports_prompt_caching,
)
from sigil.core.mcp import MCPManager, handle_search_tools_call
from sigil.core.utils import StatusCallback

logger = logging.getLogger(__name__)


def _normalize_message(msg: Any) -> dict:
    if isinstance(msg, dict):
        return msg
    if hasattr(msg, "model_dump"):
        return msg.model_dump(exclude_none=True)
    return {"role": getattr(msg, "role", "assistant"), "content": getattr(msg, "content", "") or ""}


_CLEAN_ENDINGS = (".", "!", "?", '"', "}", "]")


def _looks_truncated(content: str) -> bool:
    stripped = content.rstrip()
    if not stripped:
        return False
    return stripped[-1] not in _CLEAN_ENDINGS


_STATUS_VERBS: dict[str, str] = {
    "audit": "Auditing...",
    "ideation": "Brainstorming...",
    "validation:triager": "Triaging...",
    "validation:arbiter": "Arbitrating...",
    "engineer": "Engineering...",
    "reviewer": "Reviewing...",
    "knowledge:compact": "Studying...",
    "knowledge:incremental": "Studying...",
    "knowledge:select": "Recalling...",
    "memory:compact": "Reflecting...",
    "pr_summary": "Summarizing...",
    "engineer:summary": "Summarizing...",
}


@dataclass
class ToolResult:
    content: str
    stop: bool = False
    result: Any = None
    nudge: str | None = None


TruncationHandler = Callable[[list[dict], Any, int], bool]


@dataclass
class SubAgent:
    agent: "Agent"
    description: str
    parameters: dict


@dataclass
class AgentResult:
    messages: list[dict] = field(default_factory=list)
    doom_loop: bool = False
    rounds: int = 0
    stop_result: Any | None = None
    last_content: str = ""


class Tool:
    def __init__(
        self,
        *,
        name: str,
        description: str,
        parameters: dict,
        handler: Callable[[dict], Awaitable[ToolResult | str]],
        mutating: bool = False,
    ):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler
        self.mutating = mutating

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    async def execute(self, args: dict) -> ToolResult:
        try:
            result = await self.handler(args)
            if isinstance(result, ToolResult):
                return result
            return ToolResult(content=str(result))
        except Exception as exc:
            logger.warning("Tool %s failed: %s", self.name, exc)
            return ToolResult(content=f"Tool error: {exc}")


async def _handle_mcp_tools(
    name: str,
    args: dict,
    *,
    mcp_mgr: MCPManager | None = None,
    mcp_tool_schemas: list[dict] | None = None,
) -> ToolResult | None:
    if name == "search_tools":
        if mcp_mgr:
            result = handle_search_tools_call(mcp_mgr, args, mcp_tool_schemas or [])
            return ToolResult(content=result)
        return ToolResult(content="search_tools is not available without MCP servers.")
    if mcp_mgr and mcp_mgr.has_tool(name):
        result = await mcp_mgr.call_tool(name, args)
        return ToolResult(content=result)
    return None


class Agent:
    def __init__(
        self,
        *,
        label: str,
        model: str,
        tools: list[Tool],
        system_prompt: str,
        temperature: float = 0.0,
        max_rounds: int = 10,
        max_tokens: int | None = None,
        use_cache: bool = True,
        enable_doom_loop: bool = True,
        enable_masking: bool = True,
        enable_compaction: bool = True,
        on_truncation: TruncationHandler | None = None,
        mcp_mgr: MCPManager | None = None,
        extra_tool_schemas: list[dict] | None = None,
        tool_model: str | None = None,
        escalate_after: int = 10,
        subagents: dict[str, SubAgent] | None = None,
        forced_final_tool: str | None = None,
        reasoning_effort: str | None = None,
    ):
        self.label = label
        self.model = model
        self.tools = tools
        self.system_prompt = system_prompt
        self.temperature = temperature
        self.max_rounds = max_rounds
        self.max_tokens = max_tokens
        self.use_cache = use_cache
        self.enable_doom_loop = enable_doom_loop
        self.enable_masking = enable_masking
        self.enable_compaction = enable_compaction
        self.on_truncation = on_truncation
        self.mcp_mgr = mcp_mgr
        self.extra_tool_schemas = extra_tool_schemas or []
        self.tool_model = tool_model
        self.escalate_after = escalate_after
        self.subagents = subagents or {}
        self.forced_final_tool = forced_final_tool
        self.reasoning_effort = reasoning_effort

        self._tool_map: dict[str, Tool] = {t.name: t for t in tools}
        for sa_name, sa in self.subagents.items():
            self._tool_map[sa_name] = self._make_subagent_tool(sa_name, sa)

    def _make_subagent_tool(self, name: str, sa: SubAgent) -> Tool:
        async def _handler(args: dict) -> ToolResult:
            prompt = args.get("request", args.get("question", ""))
            if not prompt:
                prompt = json.dumps(args)
            logger.debug("%s: spawning subagent %s with: %s", self.label, name, prompt[:100])
            result = await sa.agent.run(
                messages=[{"role": "user", "content": prompt}],
            )
            response = result.stop_result or result.last_content or "(no response)"
            if isinstance(response, str):
                return ToolResult(content=response)
            return ToolResult(content=str(response))

        return Tool(
            name=name,
            description=sa.description,
            parameters=sa.parameters,
            handler=_handler,
        )

    def add_tool(self, tool: "Tool") -> None:
        if tool.name not in self._tool_map:
            self.tools.append(tool)
        self._tool_map[tool.name] = tool

    def remove_tool(self, name: str) -> None:
        self._tool_map.pop(name, None)
        self.tools = [t for t in self.tools if t.name != name]

    def _build_tool_schemas(self) -> list[dict]:
        schemas = [t.schema() for t in self.tools]
        for sa_name in self.subagents:
            schemas.append(self._tool_map[sa_name].schema())
        schemas.extend(self.extra_tool_schemas)
        return schemas

    _TOOL_BATCHING_INSTRUCTION = (
        "\n\nWhen you need to call multiple tools, make ALL calls in a single response. "
        "Do not make one call at a time — batch independent tool calls together."
    )

    def _system_message(self, context: dict[str, Any] | None = None) -> dict | None:
        if not self.system_prompt:
            return None
        prompt = self.system_prompt
        if context:
            prompt = Template(prompt).safe_substitute(context)
        if self.tools:
            prompt += self._TOOL_BATCHING_INSTRUCTION
        if supports_prompt_caching(self.model):
            return {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            }
        return {"role": "system", "content": prompt}

    async def run(
        self,
        *,
        context: dict[str, Any] | None = None,
        messages: list[dict] | None = None,
        on_status: StatusCallback | None = None,
    ) -> AgentResult:
        system_msg = self._system_message(context)

        if messages is None:
            messages = []

        if system_msg:
            if not messages or messages[0].get("role") != "system":
                messages = [system_msg] + messages
            else:
                messages[0] = system_msg

        tool_schemas = self._build_tool_schemas()
        doom_loop = False
        rounds = 0
        consecutive_truncations = 0
        last_content = ""
        last_prompt_tokens: int | None = None
        rounds_since_escalation = 0
        using_tool_model = False
        executor_misses = 0
        content_only_misses = 0

        for _ in range(self.max_rounds):
            rounds += 1

            if self.enable_doom_loop:
                doom_call = detect_doom_loop(messages)
                if doom_call is not None:
                    tool_name, tool_args = doom_call
                    truncated_args = tool_args[:500] + "..." if len(tool_args) > 500 else tool_args
                    logger.warning(
                        "Doom loop detected in %s — tool %r repeated %d times with args: %s",
                        self.label,
                        tool_name,
                        DOOM_LOOP_MAX_REPEATS,
                        truncated_args,
                    )
                    doom_loop = True
                    break

            compact_model = self.tool_model if using_tool_model else self.model
            await reduce_context(
                messages,
                compact_model,
                last_prompt_tokens=last_prompt_tokens,
                mask=self.enable_masking,
                compact=self.enable_compaction,
            )

            if on_status:
                on_status(_STATUS_VERBS.get(self.label, "Generating..."))

            if self.tool_model:
                if rounds == 2:
                    using_tool_model = True
                    rounds_since_escalation = 0
                    logger.debug("%s: switching to executor model %s", self.label, self.tool_model)
                elif not using_tool_model and rounds_since_escalation >= 1:
                    using_tool_model = True
                    rounds_since_escalation = 0
                    logger.debug("%s: returning to executor model after escalation", self.label)
                elif using_tool_model and rounds_since_escalation >= self.escalate_after:
                    using_tool_model = False
                    rounds_since_escalation = 0
                    logger.debug("%s: escalating to planner model %s", self.label, self.model)

            active_model = self.tool_model if using_tool_model else self.model
            max_tokens = safe_max_tokens(
                active_model, messages, tools=tool_schemas, requested=self.max_tokens
            )

            forced_tool_choice: dict | None = None
            if self.forced_final_tool:
                if rounds == self.max_rounds - 1:
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"Warning: 1 round remaining. You MUST call "
                                f"{self.forced_final_tool} in your next response."
                            ),
                        }
                    )
                elif rounds == self.max_rounds:
                    forced_tool_choice = {
                        "type": "function",
                        "function": {"name": self.forced_final_tool},
                    }

            extra_kwargs: dict[str, Any] = {}
            if forced_tool_choice:
                extra_kwargs["tool_choice"] = forced_tool_choice
            if self.reasoning_effort and not using_tool_model:
                extra_kwargs["reasoning_effort"] = self.reasoning_effort

            if context_pressure(
                active_model, messages, tool_schemas, last_prompt_tokens=last_prompt_tokens
            ):
                logger.warning(
                    "%s: context near limit, forcing aggressive compaction",
                    self.label,
                )
                await reduce_context(
                    messages,
                    active_model,
                    aggressive=True,
                    mask=self.enable_masking,
                    compact=self.enable_compaction,
                )

            try:
                response = await acompletion(
                    label=f"{self.label}:tool" if using_tool_model else self.label,
                    model=active_model,
                    messages=messages,
                    tools=tool_schemas,
                    parallel_tool_calls=True,
                    temperature=self.temperature,
                    max_tokens=max_tokens,
                    **extra_kwargs,
                )
            except ContextOverflowError:
                logger.warning(
                    "%s: context overflow detected, running aggressive compaction",
                    self.label,
                )
                compacted = await reduce_context(
                    messages,
                    active_model,
                    aggressive=True,
                    mask=self.enable_masking,
                    compact=self.enable_compaction,
                )
                if compacted:
                    continue
                logger.error(
                    "%s: aggressive compaction failed to reduce context, aborting",
                    self.label,
                )
                break
            rounds_since_escalation += 1

            usage = getattr(response, "usage", None)
            if usage:
                pt = getattr(usage, "prompt_tokens", None)
                if isinstance(pt, int):
                    last_prompt_tokens = pt

            choice = response.choices[0]
            last_content = getattr(choice.message, "content", None) or ""

            truncated_with_tools = False
            hit_length_cap = choice.finish_reason == "length"
            if hit_length_cap:
                if self.on_truncation:
                    consecutive_truncations += 1
                    should_continue = self.on_truncation(messages, choice, consecutive_truncations)
                    if should_continue:
                        continue
                if choice.message.tool_calls:
                    logger.warning(
                        "%s response truncated but has %d tool call(s) — processing before stopping",
                        self.label,
                        len(choice.message.tool_calls),
                    )
                    truncated_with_tools = True

            consecutive_truncations = 0

            if not choice.message.tool_calls:
                if using_tool_model:
                    executor_misses += 1
                    messages.append(_normalize_message(choice.message))
                    if executor_misses >= 2:
                        logger.debug(
                            "%s: tool model failed to make tool calls %d times — escalating",
                            self.label,
                            executor_misses,
                        )
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "The tool model stopped without making tool calls. "
                                    "Review the current state and continue working, "
                                    "or call done if the task is complete."
                                ),
                            }
                        )
                        using_tool_model = False
                        rounds_since_escalation = 0
                        executor_misses = 0
                    else:
                        messages.append(
                            {
                                "role": "user",
                                "content": "Continue — use your tools to make progress on the task.",
                            }
                        )
                    continue

                is_truncated = hit_length_cap or _looks_truncated(last_content)
                if is_truncated and content_only_misses < 2:
                    content_only_misses += 1
                    messages.append(_normalize_message(choice.message))
                    if hit_length_cap:
                        nudge = (
                            "Your previous response hit the output token limit and was cut off "
                            "before you called a tool. Your content was too long. Try again with a "
                            "shorter response — call a tool directly without narrating first, or "
                            "break large edits into smaller pieces."
                        )
                    else:
                        nudge = (
                            "Your previous response appears to have been cut off mid-thought "
                            "and contained no tool call. Continue by calling a tool to make progress, "
                            "or call the appropriate final tool if the task is complete."
                        )
                    messages.append({"role": "user", "content": nudge})
                    logger.debug(
                        "%s: truncated content-only response (attempt %d, length_cap=%s) — injecting nudge",
                        self.label,
                        content_only_misses,
                        hit_length_cap,
                    )
                    continue
                if hit_length_cap:
                    logger.debug("%s response truncated (finish_reason=length)", self.label)
                break

            messages.append(_normalize_message(choice.message))
            executor_misses = 0
            content_only_misses = 0

            stop_deferred = False
            stop_result_value = None

            async def _exec_tool_call(tc: Any) -> tuple[str, str, ToolResult]:
                func_name = tc.function.name or ""
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    return tc.id, func_name, ToolResult(content="Invalid JSON arguments.")
                record_tool_call(self.label, tc.id, func_name, tc.function.arguments)
                tool = self._tool_map.get(func_name)
                if tool:
                    result = await tool.execute(args)
                else:
                    mcp_result = await _handle_mcp_tools(
                        func_name,
                        args,
                        mcp_mgr=self.mcp_mgr,
                        mcp_tool_schemas=tool_schemas,
                    )
                    result = mcp_result if mcp_result else ToolResult(content="Unknown tool.")
                record_tool_result(self.label, tc.id, func_name, result.content)
                return tc.id, func_name, result

            read_only_calls = []
            mutating_calls = []
            for tc in choice.message.tool_calls:
                tool = self._tool_map.get(tc.function.name)
                if tool and tool.mutating:
                    mutating_calls.append(tc)
                else:
                    read_only_calls.append(tc)

            results: list[tuple[str, str, ToolResult]] = []
            if read_only_calls:
                results.extend(
                    await asyncio.gather(*[_exec_tool_call(tc) for tc in read_only_calls])
                )
            for tc in mutating_calls:
                results.append(await _exec_tool_call(tc))

            for tc_id, func_name, tool_result in results:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "name": func_name,
                        "content": tool_result.content,
                    }
                )

            nudges = [r.nudge for _, _, r in results if r.nudge]
            if nudges:
                nudge_body = "\n\n".join(nudges)
                messages.append(
                    {
                        "role": "user",
                        "content": f"System notice:\n\n{nudge_body}",
                    }
                )
                logger.debug("%s: injected %d tool nudge(s)", self.label, len(nudges))

            stop_result = next((r for _, _, r in results if r.stop), None)
            if stop_result is not None:
                stop_result_value = stop_result.result
                if using_tool_model:
                    logger.debug(
                        "%s: tool model called stop tool — escalating to planner to confirm",
                        self.label,
                    )
                    stop_deferred = True
                else:
                    return AgentResult(
                        messages=messages,
                        doom_loop=False,
                        rounds=rounds,
                        stop_result=stop_result_value,
                        last_content=last_content,
                    )

            if stop_deferred:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "The tool model indicated it is done. Review the work so far "
                            "and either call done yourself to confirm, or continue working "
                            "if something is incomplete."
                        ),
                    }
                )
                using_tool_model = False
                rounds_since_escalation = 0
                continue

            if choice.finish_reason == "stop" or truncated_with_tools:
                break

        return AgentResult(
            messages=messages,
            doom_loop=doom_loop,
            rounds=rounds,
            stop_result=None,
            last_content=last_content,
        )


class AgentCoordinator:
    def __init__(self, *, max_rounds: int = 3) -> None:
        self._agents: dict[str, Agent] = {}
        self._histories: dict[str, list[dict]] = {}
        self.max_rounds = max_rounds

    def add_agent(self, name: str, agent: Agent, initial_messages: list[dict]) -> None:
        self._agents[name] = agent
        self._histories[name] = copy.deepcopy(initial_messages)

    def has_agent(self, name: str) -> bool:
        return name in self._agents

    def inject(self, name: str, message: dict) -> None:
        if name not in self._histories:
            raise KeyError(f"Unknown agent {name!r}")
        self._histories[name].append(message)

    async def run_agent(
        self,
        name: str,
        *,
        on_status: StatusCallback | None = None,
    ) -> AgentResult:
        if name not in self._agents:
            raise KeyError(f"Unknown agent {name!r}")
        agent = self._agents[name]
        result = await agent.run(messages=self._histories[name], on_status=on_status)
        self._histories[name] = result.messages
        return result

    def get_history(self, name: str) -> list[dict]:
        if name not in self._histories:
            raise KeyError(f"Unknown agent {name!r}")
        return list(self._histories[name])
