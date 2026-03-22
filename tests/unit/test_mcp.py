import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sigil.mcp import (
    MCPManager,
    _interpolate_env,
    _interpolate_dict,
    _namespaced,
    _sanitize_name,
    _validate_server_cfg,
    connect_mcp_servers,
    format_mcp_tools_for_prompt,
    mcp_tool_to_litellm,
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
    assert _namespaced("notion", "search") == "notion__search"
    assert _namespaced("my_server", "do_thing") == "my_server__do_thing"


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
    assert result["function"]["name"] == "notion__search"
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
        {"function": {"name": "notion__search", "description": "[notion] Search pages"}},
        {"function": {"name": "slack__post", "description": "[slack] Post message"}},
    ]
    result = format_mcp_tools_for_prompt(tools)
    assert "notion__search" in result
    assert "slack__post" in result
    assert "external MCP tools" in result


def test_manager_add_server_and_get_tools():
    mgr = MCPManager()
    session = MagicMock()
    tools = [_make_mock_tool("read"), _make_mock_tool("write")]
    mgr.add_server("fs", session, tools)

    assert mgr.server_count == 1
    assert mgr.tool_count == 2
    assert mgr.has_tool("fs__read")
    assert mgr.has_tool("fs__write")
    assert not mgr.has_tool("read")

    litellm_tools = mgr.get_tools()
    assert len(litellm_tools) == 2
    names = {t["function"]["name"] for t in litellm_tools}
    assert names == {"fs__read", "fs__write"}


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

    result = await mgr.call_tool("notion__search", {"q": "test"})
    assert result == "result text"
    session.call_tool.assert_called_once_with("search", {"q": "test"})


async def test_manager_call_tool_unknown():
    mgr = MCPManager()
    result = await mgr.call_tool("nonexistent__tool", {})
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
    result = await mgr.call_tool("srv__big", {})
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
        result = await mgr.call_tool("srv__slow", {})
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
        mgr.call_tool("srv__a", {}),
        mgr.call_tool("srv__b", {}),
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
