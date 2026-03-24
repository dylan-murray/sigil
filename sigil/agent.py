import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from string import Template
from typing import Any

from sigil.llm import (
    acompletion,
    cacheable_message,
    compact_messages,
    detect_doom_loop,
    get_agent_output_cap,
    mask_old_tool_outputs,
)
from sigil.mcp import MCPManager, handle_search_tools_call
from sigil.utils import StatusCallback

log = logging.getLogger(__name__)


@dataclass
class ToolResult:
    content: str
    stop: bool = False
    result: Any = None


TruncationHandler = Callable[[list[dict], Any, int], bool]


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
    ):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler

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
            log.warning("Tool %s failed: %s", self.name, exc)
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
        agent_key: str = "",
        use_cache: bool = True,
        enable_doom_loop: bool = True,
        enable_masking: bool = True,
        enable_compaction: bool = True,
        on_truncation: TruncationHandler | None = None,
        mcp_mgr: MCPManager | None = None,
        extra_tool_schemas: list[dict] | None = None,
    ):
        self.label = label
        self.model = model
        self.tools = tools
        self.system_prompt = system_prompt
        self.temperature = temperature
        self.max_rounds = max_rounds
        self.max_tokens = max_tokens
        self.agent_key = agent_key
        self.use_cache = use_cache
        self.enable_doom_loop = enable_doom_loop
        self.enable_masking = enable_masking
        self.enable_compaction = enable_compaction
        self.on_truncation = on_truncation
        self.mcp_mgr = mcp_mgr
        self.extra_tool_schemas = extra_tool_schemas or []

        self._tool_map: dict[str, Tool] = {t.name: t for t in tools}

    def _build_tool_schemas(self) -> list[dict]:
        schemas = [t.schema() for t in self.tools]
        schemas.extend(self.extra_tool_schemas)
        return schemas

    async def run(
        self,
        *,
        context: dict[str, Any] | None = None,
        messages: list[dict] | None = None,
        on_status: StatusCallback | None = None,
    ) -> AgentResult:
        if messages is None:
            prompt = self.system_prompt
            if context:
                prompt = Template(prompt).safe_substitute(context)

            if self.use_cache:
                initial_msg = cacheable_message(self.model, prompt)
            else:
                initial_msg = {"role": "user", "content": prompt}

            messages = [initial_msg]

        tool_schemas = self._build_tool_schemas()
        doom_loop = False
        rounds = 0
        consecutive_truncations = 0
        last_content = ""

        for _ in range(self.max_rounds):
            rounds += 1

            if self.enable_doom_loop and detect_doom_loop(messages):
                log.warning("Doom loop detected in %s — breaking", self.label)
                doom_loop = True
                break

            if self.enable_masking:
                mask_old_tool_outputs(messages)

            if self.enable_compaction:
                await compact_messages(messages, self.model)

            if on_status:
                on_status("Generating...")

            max_tokens = self.max_tokens or get_agent_output_cap(self.agent_key, self.model)

            response = await acompletion(
                label=self.label,
                model=self.model,
                messages=messages,
                tools=tool_schemas,
                temperature=self.temperature,
                max_tokens=max_tokens,
            )

            choice = response.choices[0]
            last_content = getattr(choice.message, "content", None) or ""

            if choice.finish_reason == "length":
                if self.on_truncation:
                    consecutive_truncations += 1
                    should_continue = self.on_truncation(messages, choice, consecutive_truncations)
                    if should_continue:
                        continue
                if not choice.message.tool_calls:
                    log.warning("%s response truncated (finish_reason=length)", self.label)
                break

            consecutive_truncations = 0

            if not choice.message.tool_calls:
                break

            messages.append(choice.message)

            for tool_call in choice.message.tool_calls:
                name = tool_call.function.name
                try:
                    args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": "Invalid JSON arguments.",
                        }
                    )
                    continue

                tool = self._tool_map.get(name)
                if tool:
                    tool_result = await tool.execute(args)
                else:
                    tool_result = await _handle_mcp_tools(
                        name,
                        args,
                        mcp_mgr=self.mcp_mgr,
                        mcp_tool_schemas=tool_schemas,
                    )

                if tool_result is None:
                    tool_result = ToolResult(content="Unknown tool.")

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": tool_result.content,
                    }
                )

                if tool_result.stop:
                    return AgentResult(
                        messages=messages,
                        doom_loop=False,
                        rounds=rounds,
                        stop_result=tool_result.result,
                        last_content=last_content,
                    )

            if choice.finish_reason == "stop":
                break

        return AgentResult(
            messages=messages,
            doom_loop=doom_loop,
            rounds=rounds,
            stop_result=None,
            last_content=last_content,
        )
