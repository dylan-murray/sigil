import asyncio
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client

from sigil.core.config import Config
from sigil.core.llm import get_context_window
from sigil.core.utils import expand_env_vars

logger = logging.getLogger(__name__)

MCP_CONNECT_TIMEOUT = 60
MCP_CALL_TIMEOUT = 30
MCP_RESULT_MAX_CHARS = 8000

DEFERRED_MIN_TOOLS = 10
DEFERRED_CONTEXT_RATIO = 0.10

SEARCH_TOOLS_TOOL = {
    "type": "function",
    "function": {
        "name": "search_tools",
        "description": (
            "Search available MCP tools by name or description. Returns full "
            "parameter schemas for matching tools so you can call them."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query to match against tool names and descriptions.",
                },
            },
            "required": ["query"],
        },
    },
}

_VALID_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")
_SANITIZE_RE = re.compile(r"[^a-z0-9_]")


def _interpolate_dict(d: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, str):
            out[k] = expand_env_vars(v, strict=True)
        elif isinstance(v, dict):
            out[k] = _interpolate_dict(v)
        elif isinstance(v, list):
            out[k] = [expand_env_vars(i, strict=True) if isinstance(i, str) else i for i in v]
        else:
            out[k] = v
    return out


def _sanitize_name(raw: str) -> str:
    return _SANITIZE_RE.sub("_", raw.lower()).strip("_")


def _validate_server_cfg(cfg: dict, seen_names: set[str]) -> str:
    name = cfg.get("name")
    if not name or not isinstance(name, str):
        raise ValueError("MCP server entry missing required 'name' field")

    if not _VALID_NAME_RE.match(name):
        raise ValueError(f"MCP server name {name!r} must match [a-zA-Z][a-zA-Z0-9_-]*")

    sanitized = _sanitize_name(name)
    if "__" in sanitized:
        raise ValueError(
            f"MCP server name {name!r} must not contain double underscores "
            f"(reserved as tool name separator)"
        )
    if sanitized in seen_names:
        raise ValueError(f"Duplicate MCP server name: {name!r}")
    seen_names.add(sanitized)

    has_command = "command" in cfg
    has_url = "url" in cfg
    if not has_command and not has_url:
        raise ValueError(f"MCP server {name!r}: must have either 'command' (stdio) or 'url' (SSE)")
    if has_command and has_url:
        raise ValueError(f"MCP server {name!r}: cannot have both 'command' and 'url'")

    return sanitized


def _namespaced(server_name: str, tool_name: str) -> str:
    return f"mcp__{server_name}__{tool_name}"


def mcp_tool_to_litellm(server_name: str, tool: Any) -> dict:
    return {
        "type": "function",
        "function": {
            "name": _namespaced(server_name, tool.name),
            "description": f"[{server_name}] {tool.description or ''}",
            "parameters": tool.inputSchema
            if tool.inputSchema
            else {"type": "object", "properties": {}},
        },
    }


def format_mcp_tools_for_prompt(
    tools: list[dict], server_purposes: dict[str, str] | None = None
) -> str:
    if not tools:
        return ""
    purposes = server_purposes or {}
    if not purposes:
        lines = [
            "\nYou also have access to external MCP tools. Use them when they would "
            "help you gather information or take actions relevant to the task:\n"
        ]
        for tool in tools:
            fn = tool["function"]
            lines.append(f"- {fn['name']}: {fn['description']}")
        return "\n".join(lines)

    by_server: dict[str, list[dict]] = {}
    for tool in tools:
        name = tool["function"]["name"]
        parts = name.split("__", 2)
        server = parts[1] if len(parts) >= 3 else "unknown"
        by_server.setdefault(server, []).append(tool)

    lines = ["\nYou have access to external MCP tools from the following servers:\n"]
    for server, server_tools in by_server.items():
        purpose = purposes.get(server)
        if purpose:
            lines.append(f"**{server}** — {purpose}:")
        else:
            lines.append(f"**{server}**:")
        for tool in server_tools:
            fn = tool["function"]
            lines.append(f"  - {fn['name']}: {fn['description']}")
    return "\n".join(lines)


def estimate_tool_tokens(tools: list[dict]) -> int:
    return sum(len(json.dumps(t)) for t in tools) // 4


def format_deferred_mcp_tools_for_prompt(
    summaries: list[dict], server_purposes: dict[str, str] | None = None
) -> str:
    if not summaries:
        return ""
    purposes = server_purposes or {}

    lines = [
        "\nYou have access to external MCP tools, but their full schemas are deferred. "
        "Call `search_tools` with a query to get full parameter schemas before "
        "using any MCP tool.\n\nAvailable tools (name and description only):\n"
    ]

    if purposes:
        by_server: dict[str, list[dict]] = {}
        for s in summaries:
            parts = s["name"].split("__", 2)
            server = parts[1] if len(parts) >= 3 else "unknown"
            by_server.setdefault(server, []).append(s)

        for server, server_tools in by_server.items():
            purpose = purposes.get(server)
            if purpose:
                lines.append(f"**{server}** — {purpose}:")
            else:
                lines.append(f"**{server}**:")
            for t in server_tools:
                lines.append(f"  - {t['name']}: {t['description']}")
    else:
        for s in summaries:
            lines.append(f"- {s['name']}: {s['description']}")

    return "\n".join(lines)


class MCPManager:
    def __init__(self) -> None:
        self._sessions: dict[str, ClientSession] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._tool_map: dict[str, tuple[str, str]] = {}
        self._tools: list[dict] = []
        self._server_purposes: dict[str, str] = {}

    def add_server(
        self, name: str, session: ClientSession, tools: list[Any], purpose: str = ""
    ) -> None:
        self._sessions[name] = session
        self._locks[name] = asyncio.Lock()
        if purpose:
            self._server_purposes[name] = purpose
        for tool in tools:
            namespaced = _namespaced(name, tool.name)
            if namespaced in self._tool_map:
                existing_server, _ = self._tool_map[namespaced]
                raise ValueError(
                    f"MCP tool name collision: '{namespaced}' from server '{name}' "
                    f"conflicts with server '{existing_server}'"
                )
            litellm_tool = mcp_tool_to_litellm(name, tool)
            self._tools.append(litellm_tool)
            self._tool_map[namespaced] = (name, tool.name)

    def get_tools(self) -> list[dict]:
        return list(self._tools)

    def has_tool(self, name: str) -> bool:
        return name in self._tool_map

    async def call_tool(self, name: str, arguments: dict) -> str:
        mapping = self._tool_map.get(name)
        if mapping is None:
            return f"Unknown MCP tool: {name}"
        server_name, original_tool_name = mapping
        session = self._sessions[server_name]
        lock = self._locks[server_name]
        try:
            async with lock:
                result = await asyncio.wait_for(
                    session.call_tool(original_tool_name, arguments),
                    timeout=MCP_CALL_TIMEOUT,
                )
        except asyncio.TimeoutError:
            return f"MCP tool '{name}' timed out after {MCP_CALL_TIMEOUT}s"
        except Exception as e:
            return f"MCP tool '{name}' failed: {e}"
        parts = []
        for content in result.content:
            if hasattr(content, "text"):
                parts.append(content.text)
            else:
                parts.append(json.dumps(content.model_dump()))
        output = "\n".join(parts) if parts else "(empty result)"
        if len(output) > MCP_RESULT_MAX_CHARS:
            output = (
                output[:MCP_RESULT_MAX_CHARS] + f"\n\n... truncated ({len(output)} chars total)"
            )
        return output

    @property
    def server_count(self) -> int:
        return len(self._sessions)

    @property
    def tool_count(self) -> int:
        return len(self._tools)

    @property
    def server_purposes(self) -> dict[str, str]:
        return dict(self._server_purposes)

    def should_defer(self, model: str) -> bool:
        if self.tool_count < DEFERRED_MIN_TOOLS:
            return False
        ctx = get_context_window(model)
        return estimate_tool_tokens(self._tools) > ctx * DEFERRED_CONTEXT_RATIO

    def get_tool_summaries(self) -> list[dict]:
        return [
            {
                "name": t["function"]["name"],
                "description": t["function"]["description"],
            }
            for t in self._tools
        ]

    def search_tools(self, query: str) -> list[dict]:
        q = query.lower()
        results = []
        for tool in self._tools:
            fn = tool["function"]
            if q in fn["name"].lower() or q in fn.get("description", "").lower():
                results.append(tool)
        return results


def prepare_mcp_for_agent(
    mcp_mgr: MCPManager | None, model: str
) -> tuple[list[dict], list[dict], str]:
    if not mcp_mgr or mcp_mgr.tool_count == 0:
        return [], [], ""

    if mcp_mgr.should_defer(model):
        summaries = mcp_mgr.get_tool_summaries()
        prompt_section = format_deferred_mcp_tools_for_prompt(summaries, mcp_mgr.server_purposes)
        return [SEARCH_TOOLS_TOOL], [], prompt_section

    tools = mcp_mgr.get_tools()
    prompt_section = format_mcp_tools_for_prompt(tools, mcp_mgr.server_purposes)
    return [], tools, prompt_section


def handle_search_tools_call(mcp_mgr: MCPManager, args: dict, active_tools: list[dict]) -> str:
    query = str(args.get("query", ""))
    results = mcp_mgr.search_tools(query)
    if not results:
        return json.dumps({"tools": [], "message": f"No tools matching '{query}'"})

    existing_names = {t["function"]["name"] for t in active_tools}
    new_tools = [t for t in results if t["function"]["name"] not in existing_names]
    active_tools.extend(new_tools)

    tool_summaries = [
        {"name": t["function"]["name"], "description": t["function"]["description"]}
        for t in results
    ]
    return json.dumps({"tools": tool_summaries, "schemas_loaded": len(new_tools)})


async def _cleanup_cms(cms: list[Any], name: str) -> None:
    for cm in reversed(cms):
        try:
            await cm.__aexit__(None, None, None)
        except Exception as cleanup_err:
            logger.debug(f"Error cleaning up '{name}': {cleanup_err}")


async def _connect_one(
    server_cfg: dict,
    sanitized_name: str,
    manager: MCPManager,
    exit_stacks: list[Any],
) -> None:
    server_cfg = _interpolate_dict(server_cfg)
    purpose = server_cfg.get("purpose", "")
    name = sanitized_name
    raw_timeout = server_cfg.get("timeout", MCP_CONNECT_TIMEOUT)
    try:
        timeout = float(raw_timeout)
    except (TypeError, ValueError) as e:
        raise ValueError(f"MCP server '{name}': invalid timeout {raw_timeout!r}: {e}") from e

    local_cms: list[Any] = []

    async def _do_connect() -> None:
        if "command" in server_cfg:
            params = StdioServerParameters(
                command=server_cfg["command"],
                args=server_cfg.get("args", []),
                env={**os.environ, **server_cfg.get("env", {})},
            )
            cm = stdio_client(params)
            read_stream, write_stream = await cm.__aenter__()
            local_cms.append(cm)

            session_cm = ClientSession(read_stream, write_stream)
            session = await session_cm.__aenter__()
            local_cms.append(session_cm)

            await session.initialize()
            tools_result = await session.list_tools()
            manager.add_server(name, session, tools_result.tools, purpose=purpose)
            logger.info(f"MCP server '{name}' connected: {len(tools_result.tools)} tool(s)")

        else:
            headers = server_cfg.get("headers", {})
            cm = sse_client(server_cfg["url"], headers=headers)
            read_stream, write_stream = await cm.__aenter__()
            local_cms.append(cm)

            session_cm = ClientSession(read_stream, write_stream)
            session = await session_cm.__aenter__()
            local_cms.append(session_cm)

            await session.initialize()
            tools_result = await session.list_tools()
            manager.add_server(name, session, tools_result.tools, purpose=purpose)
            logger.info(f"MCP server '{name}' connected: {len(tools_result.tools)} tool(s)")

    try:
        await asyncio.wait_for(_do_connect(), timeout=timeout)
        exit_stacks.extend(local_cms)
    except BaseException as e:
        await _cleanup_cms(local_cms, name)

        if isinstance(e, asyncio.CancelledError):
            raise
        if isinstance(e, asyncio.TimeoutError):
            logger.warning(f"MCP server '{name}' timed out after {timeout}s")
        else:
            logger.warning(f"MCP server '{name}' failed to connect: {e}")


@asynccontextmanager
async def connect_mcp_servers(config: Config) -> AsyncIterator[MCPManager]:
    manager = MCPManager()
    exit_stacks: list[Any] = []

    try:
        seen_names: set[str] = set()
        validated: list[tuple[dict, str]] = []
        for server_cfg in config.mcp_servers:
            sanitized = _validate_server_cfg(server_cfg, seen_names)
            validated.append((server_cfg, sanitized))

        for server_cfg, sanitized in validated:
            await _connect_one(server_cfg, sanitized, manager, exit_stacks)

        yield manager

    finally:
        for cm in reversed(exit_stacks):
            try:
                await cm.__aexit__(None, None, None)
            except Exception as e:
                logger.debug(f"Error closing MCP connection: {e}")
