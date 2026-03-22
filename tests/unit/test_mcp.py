import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sigil.mcp import (
    MCPManager,
    SEARCH_TOOLS_TOOL,
    _interpolate_env,
    _interpolate_dict,
    _namespaced,
    _sanitize_name,
    _validate_server_cfg,
    connect_mcp_servers,
    estimate_tool_tokens,
    format_mcp_tools_for_prompt,
    handle_search_tools_call,
    mcp_tool_to_litellm,
    prepare_mcp_for_agent,
)
from sigil.config import Config


def test_interpolate_env_resolves_set_var():
    with patch.dict("os.environ", {"FOO": "bar"}):
        assert _interpolate_env("prefix-${FOO}-suffix") == "prefix-bar-suffix"


def test_interpolate_env_raises_on_missing_var():
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError, match="MY_SECRET.*not set"):
            _interpolate_env("${MY_SECRET}")


def test_interpolate_env_no_vars_passthrough():
    assert _interpolate_env("no vars here") == "no vars here"


def test_interpolate_dict_recursive():
    with patch.dict("os.environ", {"A": "1", "B": "2"}):
        d = {"key": "${A}", "nested": {"deep": "${B}"}, "list": ["${A}", "plain"]}
        result = _interpolate_dict(d)
        assert result == {"key": "1", "nested": {"deep": "2"}, "list": ["1", "plain"]}


def test_sanitize_name():
    assert _sanitize_name("My Cool Server") == "my_cool_server"
    assert _sanitize_name("notion") == "notion"
    assert _sanitize_name("my-server-2") == "my_server_2"


def test_sanitize_name_preserves_double_underscores():
    assert _sanitize_name("foo--bar") == "foo__bar"
    assert _sanitize_name("a  b") == "a__b"


def test_validate_server_cfg_missing_name():
    with pytest.raises(ValueError, match="missing required 'name'"):
        _validate_server_cfg({"command": "npx"}, set())


def test_validate_server_cfg_invalid_name():
    with pytest.raises(ValueError, match="must match"):
        _validate_server_cfg({"name": "123bad", "command": "npx"}, set())


def test_validate_server_cfg_duplicate_name():
    seen: set[str] = set()
    _validate_server_cfg({"name": "notion", "command": "npx"}, seen)
    with pytest.raises(ValueError, match="Duplicate"):
        _validate_server_cfg({"name": "notion", "url": "http://x"}, seen)


def test_validate_server_cfg_double_underscore_rejected():
    with pytest.raises(ValueError, match="double underscores"):
        _validate_server_cfg({"name": "foo--bar", "command": "npx"}, set())


def test_validate_server_cfg_no_transport():
    with pytest.raises(ValueError, match="must have either"):
        _validate_server_cfg({"name": "broken"}, set())


def test_validate_server_cfg_both_transports():
    with pytest.raises(ValueError, match="cannot have both"):
        _validate_server_cfg({"name": "broken", "command": "npx", "url": "http://x"}, set())


def test_validate_server_cfg_valid_stdio():
    sanitized = _validate_server_cfg(
        {"name": "myserver", "command": "npx", "args": ["-y", "pkg"]}, set()
    )
    assert sanitized == "myserver"


def test_validate_server_cfg_valid_sse():
    sanitized = _validate_server_cfg({"name": "remote", "url": "http://localhost:3000/sse"}, set())
    assert sanitized == "remote"


def test_namespaced():
    assert _namespaced("notion", "search") == "mcp__notion__search"
    assert _namespaced("my_server", "do_thing") == "mcp__my_server__do_thing"


def _make_mock_tool(name: str, description: str = "A tool", schema: dict | None = None):
    tool = MagicMock()
    tool.name = name
    tool.description = description
    tool.inputSchema = schema or {"type": "object", "properties": {"q": {"type": "string"}}}
    return tool


def test_mcp_tool_to_litellm():
    tool = _make_mock_tool("search", "Search things")
    result = mcp_tool_to_litellm("notion", tool)
    assert result["type"] == "function"
    assert result["function"]["name"] == "mcp__notion__search"
    assert result["function"]["description"] == "[notion] Search things"
    assert result["function"]["parameters"]["type"] == "object"


def test_mcp_tool_to_litellm_no_schema():
    tool = _make_mock_tool("ping", "Ping")
    tool.inputSchema = None
    result = mcp_tool_to_litellm("server", tool)
    assert result["function"]["parameters"] == {"type": "object", "properties": {}}


def test_format_mcp_tools_for_prompt_empty():
    assert format_mcp_tools_for_prompt([]) == ""


def test_format_mcp_tools_for_prompt_lists_tools():
    tools = [
        {"function": {"name": "mcp__notion__search", "description": "[notion] Search pages"}},
        {"function": {"name": "mcp__slack__post", "description": "[slack] Post message"}},
    ]
    result = format_mcp_tools_for_prompt(tools)
    assert "mcp__notion__search" in result
    assert "mcp__slack__post" in result
    assert "external MCP tools" in result


def test_format_mcp_tools_for_prompt_with_purposes():
    tools = [
        {"function": {"name": "mcp__notion__search", "description": "[notion] Search pages"}},
        {"function": {"name": "mcp__notion__create", "description": "[notion] Create page"}},
        {"function": {"name": "mcp__slack__post", "description": "[slack] Post message"}},
    ]
    purposes = {"notion": "product requirements and design docs", "slack": "team communication"}
    result = format_mcp_tools_for_prompt(tools, server_purposes=purposes)
    assert "**notion** — product requirements and design docs:" in result
    assert "**slack** — team communication:" in result
    assert "mcp__notion__search" in result
    assert "mcp__slack__post" in result
    assert "Use them when they would" not in result


def test_format_mcp_tools_for_prompt_partial_purposes():
    tools = [
        {"function": {"name": "mcp__notion__search", "description": "[notion] Search pages"}},
        {"function": {"name": "mcp__slack__post", "description": "[slack] Post message"}},
    ]
    purposes = {"notion": "product docs"}
    result = format_mcp_tools_for_prompt(tools, server_purposes=purposes)
    assert "**notion** — product docs:" in result
    assert "**slack**:" in result


def test_manager_server_purposes():
    mgr = MCPManager()
    session = MagicMock()
    mgr.add_server("notion", session, [_make_mock_tool("search")], purpose="product docs")
    mgr.add_server("slack", session, [_make_mock_tool("post")])
    assert mgr.server_purposes == {"notion": "product docs"}


def test_manager_add_server_and_get_tools():
    mgr = MCPManager()
    session = MagicMock()
    tools = [_make_mock_tool("read"), _make_mock_tool("write")]
    mgr.add_server("fs", session, tools)

    assert mgr.server_count == 1
    assert mgr.tool_count == 2
    assert mgr.has_tool("mcp__fs__read")
    assert mgr.has_tool("mcp__fs__write")
    assert not mgr.has_tool("read")

    litellm_tools = mgr.get_tools()
    assert len(litellm_tools) == 2
    names = {t["function"]["name"] for t in litellm_tools}
    assert names == {"mcp__fs__read", "mcp__fs__write"}


def test_manager_add_server_duplicate_tool_raises():
    mgr = MCPManager()
    session = MagicMock()
    mgr.add_server("srv", session, [_make_mock_tool("read")])
    with pytest.raises(ValueError, match="tool name collision"):
        mgr.add_server("srv", session, [_make_mock_tool("read")])


async def test_manager_call_tool_routes_correctly():
    mgr = MCPManager()
    session = AsyncMock()

    text_content = MagicMock()
    text_content.text = "result text"
    call_result = MagicMock()
    call_result.content = [text_content]
    session.call_tool.return_value = call_result

    tools = [_make_mock_tool("search")]
    mgr.add_server("notion", session, tools)

    result = await mgr.call_tool("mcp__notion__search", {"q": "test"})
    assert result == "result text"
    session.call_tool.assert_called_once_with("search", {"q": "test"})


async def test_manager_call_tool_unknown():
    mgr = MCPManager()
    result = await mgr.call_tool("mcp__nonexistent__tool", {})
    assert "Unknown MCP tool" in result


async def test_manager_call_tool_truncates_large_result():
    mgr = MCPManager()
    session = AsyncMock()

    text_content = MagicMock()
    text_content.text = "x" * 20000
    call_result = MagicMock()
    call_result.content = [text_content]
    session.call_tool.return_value = call_result

    mgr.add_server("srv", session, [_make_mock_tool("big")])
    result = await mgr.call_tool("mcp__srv__big", {})
    assert "truncated" in result
    assert "20000 chars" in result
    assert len(result) < 20000


async def test_manager_call_tool_timeout():
    mgr = MCPManager()
    session = AsyncMock()

    async def hang_forever(name, args):
        await asyncio.sleep(999)

    session.call_tool.side_effect = hang_forever
    mgr.add_server("srv", session, [_make_mock_tool("slow")])

    with patch("sigil.mcp.MCP_CALL_TIMEOUT", 0.05):
        result = await mgr.call_tool("mcp__srv__slow", {})
    assert "timed out" in result


async def test_manager_call_tool_serialized():
    mgr = MCPManager()
    session = AsyncMock()
    peak_active = [0]
    active = [0]

    async def tracked_call(name, args):
        active[0] += 1
        peak_active[0] = max(peak_active[0], active[0])
        await asyncio.sleep(0.02)
        active[0] -= 1
        text = MagicMock()
        text.text = "ok"
        result = MagicMock()
        result.content = [text]
        return result

    session.call_tool.side_effect = tracked_call
    tools = [_make_mock_tool("a"), _make_mock_tool("b")]
    mgr.add_server("srv", session, tools)

    await asyncio.gather(
        mgr.call_tool("mcp__srv__a", {}),
        mgr.call_tool("mcp__srv__b", {}),
    )

    assert peak_active[0] == 1


async def test_connect_mcp_servers_no_servers():
    config = Config()
    async with connect_mcp_servers(config) as mgr:
        assert mgr.server_count == 0
        assert mgr.tool_count == 0
        assert mgr.get_tools() == []


async def test_connect_mcp_servers_validation_fails_early():
    config = Config(mcp_servers=[{"command": "npx"}])
    with pytest.raises(ValueError, match="missing required 'name'"):
        async with connect_mcp_servers(config) as _mgr:
            pass


async def test_connect_mcp_servers_duplicate_names_fails():
    config = Config(
        mcp_servers=[
            {"name": "srv", "command": "echo"},
            {"name": "srv", "command": "echo"},
        ]
    )
    with pytest.raises(ValueError, match="Duplicate"):
        async with connect_mcp_servers(config) as _mgr:
            pass


def _build_mgr(tool_count: int, schema_size: int = 200) -> MCPManager:
    mgr = MCPManager()
    session = MagicMock()
    big_schema = {
        "type": "object",
        "properties": {f"param_{i}": {"type": "string"} for i in range(schema_size)},
    }
    tools = [
        _make_mock_tool(f"tool_{i}", f"Description for tool {i}", big_schema)
        for i in range(tool_count)
    ]
    mgr.add_server("srv", session, tools)
    return mgr


def test_should_defer_below_min_tools():
    mgr = _build_mgr(5, schema_size=500)
    assert not mgr.should_defer("anthropic/claude-sonnet-4-6-20250325")


def test_should_defer_above_threshold():
    mgr = _build_mgr(15, schema_size=500)
    assert mgr.should_defer("anthropic/claude-sonnet-4-6-20250325")


def test_search_tools_case_insensitive():
    mgr = MCPManager()
    session = MagicMock()
    mgr.add_server(
        "srv",
        session,
        [
            _make_mock_tool("search_docs", "Search documentation"),
            _make_mock_tool("post_message", "Post a Slack message"),
            _make_mock_tool("find_users", "Find users in the DATABASE"),
        ],
    )
    by_name = mgr.search_tools("search")
    assert len(by_name) == 1
    assert by_name[0]["function"]["name"] == "mcp__srv__search_docs"

    by_desc = mgr.search_tools("database")
    assert len(by_desc) == 1
    assert by_desc[0]["function"]["name"] == "mcp__srv__find_users"


@pytest.mark.parametrize(
    "tool_count,schema_size,expect_deferred",
    [
        (5, 10, False),
        (15, 500, True),
    ],
)
def test_prepare_mcp_for_agent_inline_vs_deferred(tool_count, schema_size, expect_deferred):
    mgr = _build_mgr(tool_count, schema_size)
    extra_builtins, mcp_tools, prompt = prepare_mcp_for_agent(
        mgr, "anthropic/claude-sonnet-4-6-20250325"
    )

    if expect_deferred:
        assert extra_builtins == [SEARCH_TOOLS_TOOL]
        assert mcp_tools == []
        assert "search_tools" in prompt
    else:
        assert extra_builtins == []
        assert len(mcp_tools) == tool_count
        assert "deferred" not in prompt


def test_handle_search_tools_call_dedup():
    mgr = MCPManager()
    session = MagicMock()
    mgr.add_server(
        "srv",
        session,
        [
            _make_mock_tool("alpha", "Alpha tool"),
            _make_mock_tool("beta", "Beta tool"),
        ],
    )
    existing_tool = mgr.get_tools()[0]
    active_tools = [existing_tool]

    handle_search_tools_call(mgr, {"query": ""}, active_tools)
    names = [t["function"]["name"] for t in active_tools]
    assert names.count("mcp__srv__alpha") == 1
    assert "mcp__srv__beta" in names
    assert len(active_tools) == 2


def test_deferred_mode_reduces_token_payload():
    mgr = _build_mgr(15, schema_size=500)
    inline_tokens = estimate_tool_tokens(mgr.get_tools())

    summaries = mgr.get_tool_summaries()
    summary_tools = [
        {"type": "function", "function": {"name": s["name"], "description": s["description"]}}
        for s in summaries
    ]
    deferred_tokens = estimate_tool_tokens(summary_tools + [SEARCH_TOOLS_TOOL])

    assert deferred_tokens < inline_tokens * 0.5
