import pytest

from sigil.core.agent import ToolResult
from sigil.pipeline.scratchpad import Scratchpad, ScratchpadEntry, make_scratchpad_append_tool


class TestScratchpad:
    def test_empty_scratchpad_format_returns_empty_string(self):
        sp = Scratchpad()
        assert sp.format_for_prompt() == ""

    def test_snapshot_returns_same_as_format_for_prompt(self):
        sp = Scratchpad()
        sp.append("auditor", "Found 3 issues")
        assert sp.snapshot() == sp.format_for_prompt()

    def test_append_single_entry(self):
        sp = Scratchpad()
        sp.append("auditor", "Found 3 issues")
        result = sp.format_for_prompt()
        assert "## Cross-Agent Scratchpad" in result
        assert "**auditor**" in result
        assert "Found 3 issues" in result

    def test_append_multiple_entries(self):
        sp = Scratchpad()
        sp.append("auditor", "Found 3 issues")
        sp.append("ideation", "Proposed 5 ideas")
        result = sp.format_for_prompt()
        assert "**auditor**" in result
        assert "**ideation**" in result
        assert "Found 3 issues" in result
        assert "Proposed 5 ideas" in result

    def test_entries_are_tagged_with_correct_source(self):
        sp = Scratchpad()
        sp.append("architect", "Plan created")
        sp.append("engineer", "Implementation done")
        entries = sp.entries
        assert entries[0].source == "architect"
        assert entries[0].message == "Plan created"
        assert entries[1].source == "engineer"
        assert entries[1].message == "Implementation done"

    def test_format_for_prompt_preserves_order(self):
        sp = Scratchpad()
        sp.append("auditor", "First note")
        sp.append("ideation", "Second note")
        sp.append("validation", "Third note")
        result = sp.format_for_prompt()
        first_pos = result.index("First note")
        second_pos = result.index("Second note")
        third_pos = result.index("Third note")
        assert first_pos < second_pos < third_pos

    def test_append_only_no_edit_or_delete(self):
        sp = Scratchpad()
        sp.append("auditor", "Note A")
        sp.append("auditor", "Note B")
        assert len(sp.entries) == 2
        assert sp.entries[0].message == "Note A"
        assert sp.entries[1].message == "Note B"


class TestScratchpadEntry:
    def test_entry_fields(self):
        entry = ScratchpadEntry(source="auditor", message="Found 3 issues")
        assert entry.source == "auditor"
        assert entry.message == "Found 3 issues"


class TestMakeScratchpadAppendTool:
    @pytest.mark.asyncio
    async def test_tool_appends_to_scratchpad(self):
        sp = Scratchpad()
        tool = make_scratchpad_append_tool(sp, source="auditor")
        result = await tool.handler({"message": "Found 3 issues"})
        assert isinstance(result, ToolResult)
        assert "auditor" in result.content
        assert len(sp.entries) == 1
        assert sp.entries[0].source == "auditor"
        assert sp.entries[0].message == "Found 3 issues"

    @pytest.mark.asyncio
    async def test_tool_returns_confirmation(self):
        sp = Scratchpad()
        tool = make_scratchpad_append_tool(sp, source="engineer")
        result = await tool.handler({"message": "Implementation complete"})
        assert "engineer" in result.content
        assert sp.entries[0].message == "Implementation complete"

    @pytest.mark.asyncio
    async def test_tool_name_and_parameters(self):
        sp = Scratchpad()
        tool = make_scratchpad_append_tool(sp, source="architect")
        assert tool.name == "scratchpad_append"
        assert "message" in tool.parameters["properties"]
        assert tool.parameters["required"] == ["message"]

    @pytest.mark.asyncio
    async def test_multiple_appends_via_tool(self):
        sp = Scratchpad()
        tool = make_scratchpad_append_tool(sp, source="auditor")
        await tool.handler({"message": "Note 1"})
        await tool.handler({"message": "Note 2"})
        assert len(sp.entries) == 2
        assert sp.entries[0].message == "Note 1"
        assert sp.entries[1].message == "Note 2"

    @pytest.mark.asyncio
    async def test_tool_source_is_set_correctly(self):
        sp = Scratchpad()
        tool_a = make_scratchpad_append_tool(sp, source="auditor")
        tool_e = make_scratchpad_append_tool(sp, source="engineer")
        await tool_a.handler({"message": "Audit note"})
        await tool_e.handler({"message": "Engine note"})
        assert sp.entries[0].source == "auditor"
        assert sp.entries[1].source == "engineer"


class TestScratchpadIntegration:
    def test_format_for_prompt_with_all_stages(self):
        sp = Scratchpad()
        sp.append("auditor", "Found 5 findings: 3 PR-track, 1 issue-track, 1 skipped")
        sp.append("ideation", "Proposed 8 ideas: 6 PR-track, 2 issue-track")
        sp.append("validation", "Validated: 4 items approved for PR, 2 for issues, 1 vetoed")
        result = sp.format_for_prompt()
        assert "## Cross-Agent Scratchpad" in result
        assert "**auditor**" in result
        assert "**ideation**" in result
        assert "**validation**" in result
        assert "3 PR-track" in result
        assert "6 PR-track" in result
        assert "4 items approved for PR" in result

    def test_empty_scratchpad_does_not_produce_section(self):
        sp = Scratchpad()
        assert sp.format_for_prompt() == ""
        assert sp.snapshot() == ""

    def test_scratchpad_append_tool_integration_with_format(self):
        sp = Scratchpad()
        tool = make_scratchpad_append_tool(sp, source="auditor")
        import asyncio

        asyncio.get_event_loop().run_until_complete(tool.handler({"message": "Found 2 findings"}))
        formatted = sp.format_for_prompt()
        assert "## Cross-Agent Scratchpad" in formatted
        assert "**auditor**" in formatted
        assert "Found 2 findings" in formatted
