import asyncio
import contextvars
import functools
import hashlib
import json
import logging
import threading
import warnings
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import litellm
from litellm.exceptions import (
    APIError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)

from sigil.core.models import CallTrace, TokenUsage

litellm.suppress_debug_info = True
logging.getLogger("LiteLLM").setLevel(logging.ERROR)


def enable_verbose_logging() -> None:
    logging.getLogger("LiteLLM").setLevel(logging.DEBUG)
    litellm.suppress_debug_info = False


warnings.filterwarnings(
    "ignore",
    message="Pydantic serializer warnings",
    category=UserWarning,
    module="pydantic",
)

MAX_RETRIES = 3
INITIAL_DELAY = 1.0
BACKOFF_FACTOR = 2.0
LLM_TIMEOUT = 300
TOOL_RESULT_MAX_CHARS = 10_000
CHARS_PER_TOKEN = 3
DOOM_LOOP_WINDOW = 10
DOOM_LOOP_MAX_REPEATS = 5
DEFAULT_COMPACTION_THRESHOLD = 80_000
COMPACTION_RATIO = 0.4

_MASKED_READ = "[file contents omitted — use read_file again if needed]"
_MASKED_MCP = "[tool result omitted — call again if needed]"
_MASKED_SEARCH = "[search results omitted — call search_tools again if needed]"
_KEEP_TOOLS = frozenset({"apply_edit", "create_file", "done"})
_REPORT_TOOLS = frozenset({"report_finding", "report_idea", "review_item", "resolve_item"})
_ERROR_MARKERS = (
    "Error",
    "error",
    "Traceback",
    "not found",
    "Access denied",
    "Invalid",
    "denied",
    "failed",
)

COMPACTION_PROMPT = """\
You are a conversation compactor. Summarize the conversation below into a \
concise briefing that preserves all information an AI agent needs to continue \
its work. Include:

1. **Goal**: what the agent is trying to accomplish
2. **Progress**: what has been done so far (tools called, files read/edited, decisions made)
3. **Key findings**: important facts, file paths, code snippets, or data discovered
4. **Next steps**: what the agent should do next based on the conversation trajectory

Be specific — include file paths, function names, line numbers, and exact values. \
Do NOT include raw file contents or tool output verbatim; summarize them instead. \
Keep the summary under 2000 tokens.

<conversation>
{conversation}
</conversation>
"""

logger = logging.getLogger(__name__)


def _get_provider_response_cost(response: litellm.ModelResponse) -> float | None:
    hidden = getattr(response, "_hidden_params", None)
    if not hidden or not isinstance(hidden, dict):
        return None
    headers = hidden.get("additional_headers") or {}
    cost = headers.get("llm_provider-x-litellm-response-cost")
    if cost is not None:
        try:
            return float(cost)
        except (TypeError, ValueError):
            return None
    return None


def compute_call_cost(
    response: litellm.ModelResponse,
    model: str,
) -> float:
    provider_cost = _get_provider_response_cost(response)
    if provider_cost is not None:
        return provider_cost
    try:
        return litellm.completion_cost(completion_response=response, model=model)
    except Exception:
        logger.debug("litellm.completion_cost failed for model=%s, cost will be 0", model)
        return 0.0


_traces: list[CallTrace] = []

_current_task: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_current_task", default=None
)


def set_trace_task(task: str | None) -> contextvars.Token:
    return _current_task.set(task)


def reset_trace_task(token: contextvars.Token) -> None:
    _current_task.reset(token)


_run_started_at: str = ""
_trace_path: Path | None = None

_usage = TokenUsage()
_usage_lock = threading.Lock()


def get_usage() -> TokenUsage:
    return _usage


def get_usage_snapshot() -> tuple[int, int, float]:
    with _usage_lock:
        return _usage.calls, _usage.prompt_tokens + _usage.completion_tokens, _usage.cost_usd


def reset_usage() -> None:
    global _usage
    with _usage_lock:
        _usage = TokenUsage()


def reset_traces(repo_root: Path | None = None) -> None:
    global _run_started_at, _trace_path
    _traces.clear()
    _run_started_at = datetime.now(timezone.utc).isoformat()
    if repo_root is not None:
        traces_dir = repo_root / ".sigil" / "traces"
        traces_dir.mkdir(parents=True, exist_ok=True)
        _trace_path = traces_dir / "last-run.jsonl"
        _trace_path.write_text("")
    else:
        _trace_path = None


def get_traces() -> list[CallTrace]:
    return list(_traces)


def _extract_content(response: object) -> str | None:
    choices = getattr(response, "choices", None)
    if not choices:
        return None
    msg = getattr(choices[0], "message", None)
    if not msg:
        return None
    content = getattr(msg, "content", None)
    if not content:
        return None
    return content


def _record_trace(
    label: str,
    model: str,
    prompt_tok: int,
    completion_tok: int,
    cache_read_tok: int,
    cache_creation_tok: int,
    cost_usd: float,
    response: object | None = None,
) -> None:
    content = _extract_content(response) if response else None
    task = _current_task.get()
    trace = CallTrace(
        timestamp=datetime.now(timezone.utc).isoformat(),
        label=f"{task}:{label}" if task else label,
        model=model,
        prompt_tokens=prompt_tok,
        completion_tokens=completion_tok,
        cache_read_tokens=cache_read_tok,
        cache_creation_tokens=cache_creation_tok,
        cost_usd=cost_usd,
        task=task,
        content=content,
    )
    _traces.append(trace)
    _flush_event(
        {"type": "llm_response"} | {k: v for k, v in asdict(trace).items() if v is not None}
    )


def record_tool_call(label: str, call_id: str, name: str, arguments: str) -> None:
    task = _current_task.get()
    event: dict = {
        "type": "tool_call",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "label": f"{task}:{label}" if task else label,
        "call_id": call_id,
        "name": name,
        "arguments": arguments,
    }
    if task:
        event["task"] = task
    _flush_event(event)


def record_tool_result(label: str, call_id: str, name: str, result: str) -> None:
    task = _current_task.get()
    event: dict = {
        "type": "tool_result",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "label": f"{task}:{label}" if task else label,
        "call_id": call_id,
        "name": name,
        "result": result[:TOOL_RESULT_MAX_CHARS],
    }
    if task:
        event["task"] = task
    _flush_event(event)


def _flush_event(event: dict) -> None:
    if _trace_path is not None:
        try:
            with _trace_path.open("a") as f:
                f.write(json.dumps(event) + "\n")
        except OSError:
            pass


def write_trace_file(repo_root: Path) -> Path | None:
    if not _traces:
        return None

    traces_dir = repo_root / ".sigil" / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)
    out_path = traces_dir / "last-run.json"

    summary_by_label: dict[str, dict[str, float | int]] = {}
    for t in _traces:
        entry = summary_by_label.setdefault(
            t.label,
            {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0},
        )
        entry["calls"] += 1
        entry["prompt_tokens"] += t.prompt_tokens
        entry["completion_tokens"] += t.completion_tokens
        entry["cost_usd"] += t.cost_usd

    payload = {
        "started_at": _run_started_at,
        "total_cost_usd": sum(t.cost_usd for t in _traces),
        "total_calls": len(_traces),
        "summary_by_label": summary_by_label,
    }

    out_path.write_text(json.dumps(payload, indent=2) + "\n")
    return out_path


MODEL_OVERRIDES: dict[str, dict[str, int]] = {
    "anthropic/claude-sonnet-4-6-20250325": {
        "max_input_tokens": 200_000,
        "max_output_tokens": 64_000,
    },
    "anthropic/claude-opus-4-6-20250527": {
        "max_input_tokens": 1_000_000,
        "max_output_tokens": 32_000,
    },
    "anthropic/claude-haiku-4-5-20251001": {
        "max_input_tokens": 200_000,
        "max_output_tokens": 64_000,
    },
    "openrouter/stepfun/step-3.5-flash": {
        "max_input_tokens": 256_000,
        "max_output_tokens": 65_536,
    },
    "openrouter/stepfun/step-3.5-flash:free": {
        "max_input_tokens": 256_000,
        "max_output_tokens": 65_536,
    },
}


_openrouter_cache: dict[str, dict[str, int]] = {}
_openrouter_fetched = False


def _fetch_openrouter_models_sync() -> None:
    import urllib.request

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/models",
        headers={"Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:  # nosemgrep: dynamic-urllib-use-detected
        data = json.loads(resp.read())
    for m in data.get("data", []):
        model_id = m.get("id", "")
        top = m.get("top_provider", {})
        ctx = m.get("context_length") or top.get("context_length")
        max_out = top.get("max_completion_tokens")
        if model_id and ctx and max_out:
            _openrouter_cache[f"openrouter/{model_id}"] = {
                "max_input_tokens": ctx,
                "max_output_tokens": max_out,
            }


def _fetch_openrouter_models() -> None:
    global _openrouter_fetched
    if _openrouter_fetched:
        return
    _openrouter_fetched = True
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        loop.run_in_executor(None, _fetch_openrouter_models_sync)
        return
    try:
        _fetch_openrouter_models_sync()
    except Exception as exc:
        logger.debug("Failed to fetch OpenRouter model info: %s", exc)


def _get_model_info(model: str) -> dict:
    if model.startswith("openrouter/"):
        _fetch_openrouter_models()
        cached = _openrouter_cache.get(model)
        if cached:
            return cached

    candidates = [model]
    parts = model.split("/")
    for i in range(1, len(parts)):
        candidates.append("/".join(parts[i:]))
    for candidate in candidates:
        try:
            info = litellm.get_model_info(candidate)
        except Exception:
            continue
        if info.get("max_output_tokens") and info["max_output_tokens"] > 8_192:
            return info
    try:
        return litellm.get_model_info(model)
    except Exception:
        return {}


def get_context_window(model: str) -> int:
    override = MODEL_OVERRIDES.get(model)
    if override:
        return override["max_input_tokens"]
    info = _get_model_info(model)
    return info.get("max_input_tokens", 0) or info.get("max_tokens", 32_000)


def get_max_output_tokens(model: str) -> int:
    override = MODEL_OVERRIDES.get(model)
    if override:
        return override["max_output_tokens"]
    info = _get_model_info(model)
    return info.get("max_output_tokens", 8_192)


def _estimate_tokens(messages: list[dict], tools: list[dict] | None = None) -> int:
    total = estimate_tokens(messages)
    if tools:
        total += sum(len(json.dumps(t)) for t in tools) // 4
    return total


def safe_max_tokens(
    model: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    requested: int | None = None,
) -> int:
    context = get_context_window(model)
    model_max = get_max_output_tokens(model)
    cap = requested if requested else model_max
    input_est = _estimate_tokens(messages, tools)
    available = context - input_est
    if cap > available:
        return max(available, 1024)
    return cap


def _extract_tc(tc: object) -> tuple[str, str, str]:
    if isinstance(tc, dict):
        name = tc.get("function", {}).get("name", "")
        args = tc.get("function", {}).get("arguments", "")
        tc_id = tc.get("id", "")
    else:
        fn = getattr(tc, "function", None)
        name = getattr(fn, "name", "") if fn else ""
        args = getattr(fn, "arguments", "") if fn else ""
        tc_id = getattr(tc, "id", "")
    return name, args, tc_id


def detect_doom_loop(messages: list[dict]) -> tuple[str, str] | None:
    signatures: list[str] = []
    i = len(messages) - 1
    while i >= 0 and len(signatures) < DOOM_LOOP_WINDOW:
        msg = messages[i]
        if isinstance(msg, dict):
            role = msg.get("role", "")
            tool_calls = msg.get("tool_calls")
        else:
            role = getattr(msg, "role", "")
            tool_calls = getattr(msg, "tool_calls", None)

        if role == "assistant" and tool_calls:
            for tc in tool_calls:
                name, args, tc_id = _extract_tc(tc)
                result_content = ""
                for j in range(i + 1, min(i + 5, len(messages))):
                    rmsg = messages[j]
                    if isinstance(rmsg, dict) and rmsg.get("role") == "tool":
                        if rmsg.get("tool_call_id") == tc_id:
                            result_content = str(rmsg.get("content", ""))[:500]
                            break
                sig = hashlib.sha256(f"{name}:{args}:{result_content}".encode()).hexdigest()
                signatures.append(sig)

        i -= 1

    if len(signatures) < DOOM_LOOP_MAX_REPEATS:
        return None

    counts = Counter(signatures)
    _, most_common_count = counts.most_common(1)[0]
    if most_common_count >= DOOM_LOOP_MAX_REPEATS:
        for msg in reversed(messages):
            tool_calls = (
                msg.get("tool_calls") if isinstance(msg, dict) else getattr(msg, "tool_calls", None)
            )
            if not tool_calls:
                continue
            name, args, _ = _extract_tc(tool_calls[0])
            return (name, args)
    return None


class BudgetExceededError(Exception):
    pass


_max_budget: float | None = None


def set_budget(max_cost_usd: float) -> None:
    global _max_budget
    _max_budget = max_cost_usd


def _check_budget() -> None:
    if _max_budget is not None and _usage.cost_usd > _max_budget:
        raise BudgetExceededError(
            f"Run budget exceeded: ${_usage.cost_usd:.2f} > ${_max_budget:.2f} limit"
        )


_RETRYABLE = (
    APIError,
    InternalServerError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
    asyncio.TimeoutError,
)


async def acompletion(*, label: str = "unknown", **kwargs: Any) -> litellm.ModelResponse:
    last_exc: Exception | None = None
    model = kwargs.get("model", "unknown")
    kwargs.setdefault("timeout", LLM_TIMEOUT)
    for attempt in range(1 + MAX_RETRIES):
        try:
            response = await asyncio.wait_for(
                litellm.acompletion(**kwargs),
                timeout=kwargs.get("timeout", LLM_TIMEOUT) + 30,
            )
            usage = getattr(response, "usage", None)
            if usage:
                prompt_tok = getattr(usage, "prompt_tokens", 0) or 0
                completion_tok = getattr(usage, "completion_tokens", 0) or 0
                cache_read_tok = getattr(usage, "cache_read_input_tokens", 0) or 0
                cache_creation_tok = getattr(usage, "cache_creation_input_tokens", 0) or 0
                if not cache_read_tok:
                    ptd = getattr(usage, "prompt_tokens_details", None)
                    if ptd:
                        cache_read_tok = getattr(ptd, "cached_tokens", 0) or 0
                        if not cache_creation_tok:
                            cache_creation_tok = getattr(ptd, "cache_creation_tokens", 0) or 0
                call_cost = compute_call_cost(response, model)
                with _usage_lock:
                    _usage.record(
                        model,
                        prompt_tok,
                        completion_tok,
                        cache_read_tok,
                        cache_creation_tok,
                        call_cost,
                    )
                _record_trace(
                    label,
                    model,
                    prompt_tok,
                    completion_tok,
                    cache_read_tok,
                    cache_creation_tok,
                    call_cost,
                    response=response,
                )
                logger.debug(
                    "LLM [%s] %s: %d in / %d out / %d cache_read / %d cache_write tokens",
                    label,
                    model,
                    prompt_tok,
                    completion_tok,
                    cache_read_tok,
                    cache_creation_tok,
                )
                _check_budget()
            return response
        except (BadRequestError, NotFoundError) as exc:
            err_msg = str(exc).lower()
            if "tool_choice" in err_msg and "tool_choice" in kwargs:
                logger.debug(
                    "Model %s does not support tool_choice — removing it",
                    model,
                )
                del kwargs["tool_choice"]
                continue
            if "function calling" in err_msg and "tool_choice" in kwargs:
                logger.debug(
                    "Model %s does not support forced function calling — removing tool_choice",
                    model,
                )
                del kwargs["tool_choice"]
                continue
            raise
        except _RETRYABLE as exc:
            last_exc = exc
            if attempt == MAX_RETRIES:
                break
            delay = INITIAL_DELAY * (BACKOFF_FACTOR**attempt)
            logger.warning(
                "LLM call failed (attempt %d/%d), retrying in %.1fs: %s",
                attempt + 1,
                MAX_RETRIES + 1,
                delay,
                exc,
            )
            await asyncio.sleep(delay)
    raise last_exc  # type: ignore[misc]


@dataclass
class _ToolCallInfo:
    name: str
    arguments: str


def _build_tool_call_map(messages: list[dict]) -> dict[str, _ToolCallInfo]:
    call_map: dict[str, _ToolCallInfo] = {}
    for msg in messages:
        tool_calls = None
        if isinstance(msg, dict):
            tool_calls = msg.get("tool_calls")
        else:
            tool_calls = getattr(msg, "tool_calls", None)
        if not tool_calls:
            continue
        for tc in tool_calls:
            if isinstance(tc, dict):
                tc_id = tc.get("id", "")
                tc_name = tc.get("function", {}).get("name", "")
                tc_args = tc.get("function", {}).get("arguments", "")
            else:
                tc_id = getattr(tc, "id", "")
                fn = getattr(tc, "function", None)
                tc_name = getattr(fn, "name", "") if fn else ""
                tc_args = getattr(fn, "arguments", "") if fn else ""
            if tc_id and tc_name:
                call_map[tc_id] = _ToolCallInfo(name=tc_name, arguments=tc_args)
    return call_map


def _looks_like_error(content: str) -> bool:
    return any(marker in content for marker in _ERROR_MARKERS)


def _extract_file_path(arguments: str) -> str:
    try:
        args = json.loads(arguments)
        return args.get("file", "")
    except (json.JSONDecodeError, AttributeError):
        return ""


def _find_latest_reads(messages: list[dict], call_map: dict[str, _ToolCallInfo]) -> set[str]:
    latest: dict[str, str] = {}
    for msg in messages:
        if not isinstance(msg, dict) or msg.get("role") != "tool":
            continue
        tc_id = msg.get("tool_call_id", "")
        info = call_map.get(tc_id)
        if not info or info.name != "read_file":
            continue
        fpath = _extract_file_path(info.arguments)
        if fpath:
            latest[fpath] = tc_id
    return set(latest.values())


def mask_old_tool_outputs(messages: list[dict], *, keep_recent: int = 6) -> list[dict]:
    if len(messages) <= keep_recent:
        return messages

    cutoff = len(messages) - keep_recent
    call_map = _build_tool_call_map(messages)
    latest_read_ids = _find_latest_reads(messages, call_map)

    for i, msg in enumerate(messages):
        if not isinstance(msg, dict) or msg.get("role") != "tool":
            continue

        content = msg.get("content", "")
        if not isinstance(content, str) or len(content) < 200:
            continue

        tool_call_id = msg.get("tool_call_id", "")
        info = call_map.get(tool_call_id)
        tool_name = info.name if info else ""

        if tool_name in _KEEP_TOOLS or tool_name in _REPORT_TOOLS:
            continue

        if tool_name == "read_file" and tool_call_id not in latest_read_ids:
            msg["content"] = _MASKED_READ
            continue

        if i >= cutoff:
            continue

        if _looks_like_error(content):
            continue

        if tool_name == "read_file":
            msg["content"] = _MASKED_READ
        elif tool_name == "search_tools":
            msg["content"] = _MASKED_SEARCH
        elif tool_name.startswith("mcp__"):
            msg["content"] = _MASKED_MCP
        elif tool_name == "":
            msg["content"] = _MASKED_MCP

    return messages


def estimate_tokens(messages: list[dict]) -> int:
    total = 0
    for msg in messages:
        if isinstance(msg, dict):
            content = msg.get("content", "")
        else:
            content = getattr(msg, "content", "") or ""
        if isinstance(content, str):
            total += len(content) // 4
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    total += len(block.get("text", "")) // 4
                else:
                    total += len(str(block)) // 4
        tool_calls = (
            msg.get("tool_calls") if isinstance(msg, dict) else getattr(msg, "tool_calls", None)
        )
        if tool_calls:
            for tc in tool_calls:
                if isinstance(tc, dict):
                    args = tc.get("function", {}).get("arguments", "")
                else:
                    fn = getattr(tc, "function", None)
                    args = getattr(fn, "arguments", "") if fn else ""
                total += len(args) // 4
    return total


def _split_at_tool_boundary(messages: list[dict], keep_recent: int) -> int:
    if len(messages) <= keep_recent:
        return len(messages)
    candidate = len(messages) - keep_recent
    while candidate > 0:
        msg = messages[candidate]
        if _is_tool_result(msg):
            candidate -= 1
            continue
        role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", "")
        if role == "assistant":
            tool_calls = (
                msg.get("tool_calls") if isinstance(msg, dict) else getattr(msg, "tool_calls", None)
            )
            if tool_calls:
                candidate -= 1
                continue
        break
    return max(1, candidate)


def _is_tool_result(msg: dict | object) -> bool:
    if isinstance(msg, dict):
        return msg.get("role") == "tool"
    return getattr(msg, "role", "") == "tool"


def _messages_to_text(messages: list[dict]) -> str:
    parts: list[str] = []
    for msg in messages:
        if isinstance(msg, dict):
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
        else:
            role = getattr(msg, "role", "unknown")
            content = getattr(msg, "content", "") or ""
        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict):
                    text_parts.append(block.get("text", ""))
                else:
                    text_parts.append(str(block))
            content = "\n".join(text_parts)
        if content:
            parts.append(f"[{role}] {content[:2000]}")
        tool_calls = (
            msg.get("tool_calls") if isinstance(msg, dict) else getattr(msg, "tool_calls", None)
        )
        if tool_calls:
            for tc in tool_calls:
                if isinstance(tc, dict):
                    name = tc.get("function", {}).get("name", "?")
                    args = tc.get("function", {}).get("arguments", "")
                else:
                    fn = getattr(tc, "function", None)
                    name = getattr(fn, "name", "?") if fn else "?"
                    args = getattr(fn, "arguments", "") if fn else ""
                parts.append(f"[tool_call] {name}({args[:200]})")
    return "\n".join(parts)


def get_compaction_threshold(model: str) -> int:
    ctx = get_context_window(model)
    if ctx > 0:
        return int(ctx * COMPACTION_RATIO)
    return DEFAULT_COMPACTION_THRESHOLD


async def compact_messages(
    messages: list[dict],
    model: str,
    *,
    threshold_tokens: int | None = None,
    keep_recent: int = 5,
    last_prompt_tokens: int | None = None,
) -> bool:
    if threshold_tokens is None:
        threshold_tokens = get_compaction_threshold(model)
    token_estimate = last_prompt_tokens if last_prompt_tokens else estimate_tokens(messages)
    if token_estimate < threshold_tokens:
        return False

    split_idx = _split_at_tool_boundary(messages, keep_recent)
    if split_idx <= 1:
        return False

    old_messages = messages[:split_idx]
    conversation_text = _messages_to_text(old_messages)

    prompt = COMPACTION_PROMPT.replace("{conversation}", conversation_text)

    try:
        response = await acompletion(
            label="compaction",
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=2048,
        )
        summary = response.choices[0].message.content or ""
    except Exception as exc:
        logger.warning("Compaction failed, skipping: %s", exc)
        return False

    if not summary.strip():
        return False

    summary_msg = {
        "role": "user",
        "content": f"[COMPACTED CONTEXT — summarized from earlier conversation]\n\n{summary}",
    }

    remaining = messages[split_idx:]
    messages.clear()
    messages.append(summary_msg)
    messages.extend(remaining)

    logger.info(
        "Compacted %d messages into summary (%d tokens estimated → %d)",
        len(old_messages),
        estimate_tokens(old_messages),
        estimate_tokens(messages),
    )
    return True


@functools.lru_cache(maxsize=64)
def supports_prompt_caching(model: str) -> bool:
    from litellm.utils import supports_prompt_caching as _litellm_supports

    try:
        if _litellm_supports(model=model):
            return True
    except Exception:
        pass

    if not model.startswith("openrouter/"):
        return False

    rest = model.removeprefix("openrouter/")
    _, _, base_name = rest.partition("/")
    candidates = [rest, base_name]
    for provider in litellm.provider_list:
        candidates.append(f"{provider}/{base_name}")

    for candidate in candidates:
        if candidate == model:
            continue
        try:
            if _litellm_supports(model=candidate):
                return True
        except Exception:
            continue
    logger.debug("Could not resolve prompt caching support for OpenRouter model: %s", model)
    return False


def cacheable_message(model: str, prompt: str) -> dict:
    if supports_prompt_caching(model):
        return {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        }
    return {"role": "user", "content": prompt}
