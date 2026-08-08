import json
from pathlib import Path

from sigil.pipeline.ideation import FeatureIdea
from sigil.pipeline.maintenance import Finding
from sigil.pipeline.patterns import (
    _format_patterns_content,
    _parse_patterns_file,
    format_pattern_hints,
    load_tool_patterns,
    mine_tool_patterns,
    write_tool_patterns,
)
from sigil.state.attempts import AttemptRecord, log_attempt


def _make_finding(**kw) -> Finding:
    defaults = dict(
        category="dead_code",
        file="src/utils.py",
        line=42,
        description="Unused import",
        risk="low",
        suggested_fix="Remove it",
        disposition="pr",
        priority=1,
        rationale="Not referenced",
    )
    defaults.update(kw)
    return Finding(**defaults)


def _make_idea(**kw) -> FeatureIdea:
    defaults = dict(
        title="Add retry logic",
        description="Retry failed HTTP calls",
        rationale="Improves reliability",
        complexity="low",
        disposition="pr",
        priority=2,
    )
    defaults.update(kw)
    return FeatureIdea(**defaults)


def _write_traces(repo: Path, events: list[dict]) -> None:
    traces_dir = repo / ".sigil" / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)
    path = traces_dir / "last-run.jsonl"
    lines = [json.dumps(e) for e in events]
    path.write_text("\n".join(lines) + "\n")


def _write_attempts(repo: Path, records: list[AttemptRecord]) -> None:
    for rec in records:
        log_attempt(repo, rec)


class TestMineToolPatterns:
    def test_happy_path(self, tmp_path: Path) -> None:
        events = [
            {"type": "tool_call", "task": "dead-code-utils", "name": "read_file", "call_id": "1"},
            {"type": "tool_call", "task": "dead-code-utils", "name": "grep", "call_id": "2"},
            {"type": "tool_call", "task": "dead-code-utils", "name": "apply_edit", "call_id": "3"},
            {"type": "tool_call", "task": "dead-code-utils", "name": "create_file", "call_id": "4"},
        ]
        _write_traces(tmp_path, events)

        records = [
            AttemptRecord(
                run_id="r1",
                timestamp="2026-01-01T00:00:00Z",
                item_type="finding",
                item_id="finding:dead_code:src/utils.py",
                category="dead_code",
                complexity="",
                approach="Remove unused import",
                model="test",
                retries=0,
                outcome="success",
                tokens_used=100,
                duration_s=10.0,
                failure_detail="",
            ),
        ]
        _write_attempts(tmp_path, records)

        items = [_make_finding(category="dead_code", file="src/utils.py")]
        result = mine_tool_patterns(tmp_path, items=items)

        assert "dead_code" in result
        assert len(result["dead_code"]) == 1
        assert result["dead_code"][0] == "read_file → grep → apply_edit → create_file"

    def test_filtering_failures(self, tmp_path: Path) -> None:
        events = [
            {"type": "tool_call", "task": "security-auth", "name": "read_file", "call_id": "1"},
            {"type": "tool_call", "task": "security-auth", "name": "apply_edit", "call_id": "2"},
        ]
        _write_traces(tmp_path, events)

        records = [
            AttemptRecord(
                run_id="r1",
                timestamp="2026-01-01T00:00:00Z",
                item_type="finding",
                item_id="finding:security:src/auth.py",
                category="security",
                complexity="",
                approach="Fix auth",
                model="test",
                retries=2,
                outcome="doom_loop",
                tokens_used=200,
                duration_s=30.0,
                failure_detail="Doom loop",
            ),
        ]
        _write_attempts(tmp_path, records)

        items = [_make_finding(category="security", file="src/auth.py")]
        result = mine_tool_patterns(tmp_path, items=items)

        assert result == {}

    def test_top_k_limit(self, tmp_path: Path) -> None:
        events = []
        for i in range(10):
            task = f"dead-code-utils-{i}"
            events.extend(
                [
                    {"type": "tool_call", "task": task, "name": "read_file", "call_id": f"a{i}"},
                    {"type": "tool_call", "task": task, "name": "apply_edit", "call_id": f"b{i}"},
                ]
            )
        _write_traces(tmp_path, events)

        records = []
        for i in range(10):
            records.append(
                AttemptRecord(
                    run_id=f"r{i}",
                    timestamp="2026-01-01T00:00:00Z",
                    item_type="finding",
                    item_id=f"finding:dead_code:src/file{i}.py",
                    category="dead_code",
                    complexity="",
                    approach=f"Fix {i}",
                    model="test",
                    retries=0,
                    outcome="success",
                    tokens_used=100,
                    duration_s=10.0,
                    failure_detail="",
                )
            )
        _write_attempts(tmp_path, records)

        items = [_make_finding(category="dead_code", file="src/utils.py")]
        result = mine_tool_patterns(tmp_path, items=items, max_per_category=3)

        assert "dead_code" in result
        assert len(result["dead_code"]) <= 3

    def test_empty_trace_file(self, tmp_path: Path) -> None:
        traces_dir = tmp_path / ".sigil" / "traces"
        traces_dir.mkdir(parents=True, exist_ok=True)
        (traces_dir / "last-run.jsonl").write_text("")

        attempts_dir = tmp_path / ".sigil"
        attempts_dir.mkdir(parents=True, exist_ok=True)
        (attempts_dir / "attempts.jsonl").write_text("")

        result = mine_tool_patterns(tmp_path)
        assert result == {}

    def test_missing_files(self, tmp_path: Path) -> None:
        result = mine_tool_patterns(tmp_path)
        assert result == {}

    def test_malformed_lines_skipped(self, tmp_path: Path) -> None:
        events = [
            {"type": "tool_call", "task": "dead-code-utils", "name": "read_file", "call_id": "1"},
            {"type": "tool_call", "task": "dead-code-utils", "name": "apply_edit", "call_id": "2"},
        ]
        _write_traces(tmp_path, events)

        traces_path = tmp_path / ".sigil" / "traces" / "last-run.jsonl"
        original = traces_path.read_text()
        traces_path.write_text("not json\n" + original)

        records = [
            AttemptRecord(
                run_id="r1",
                timestamp="2026-01-01T00:00:00Z",
                item_type="finding",
                item_id="finding:dead_code:src/utils.py",
                category="dead_code",
                complexity="",
                approach="Fix",
                model="test",
                retries=0,
                outcome="success",
                tokens_used=100,
                duration_s=10.0,
                failure_detail="",
            ),
        ]
        _write_attempts(tmp_path, records)

        items = [_make_finding(category="dead_code", file="src/utils.py")]
        result = mine_tool_patterns(tmp_path, items=items)

        assert "dead_code" in result

    def test_idea_category(self, tmp_path: Path) -> None:
        events = [
            {"type": "tool_call", "task": "add-retry-logic", "name": "read_file", "call_id": "1"},
            {"type": "tool_call", "task": "add-retry-logic", "name": "create_file", "call_id": "2"},
        ]
        _write_traces(tmp_path, events)

        records = [
            AttemptRecord(
                run_id="r1",
                timestamp="2026-01-01T00:00:00Z",
                item_type="idea",
                item_id="idea:add-retry-logic",
                category="",
                complexity="low",
                approach="Add retry",
                model="test",
                retries=0,
                outcome="success",
                tokens_used=100,
                duration_s=10.0,
                failure_detail="",
            ),
        ]
        _write_attempts(tmp_path, records)

        items = [_make_idea(title="Add retry logic")]
        result = mine_tool_patterns(tmp_path, items=items)

        assert "idea" in result

    def test_deduplication_by_frequency(self, tmp_path: Path) -> None:
        events = []
        for i in range(3):
            task = f"dead-code-utils-{i}"
            events.extend(
                [
                    {"type": "tool_call", "task": task, "name": "read_file", "call_id": f"a{i}"},
                    {"type": "tool_call", "task": task, "name": "apply_edit", "call_id": f"b{i}"},
                ]
            )
        task = "dead-code-utils-3"
        events.extend(
            [
                {"type": "tool_call", "task": task, "name": "grep", "call_id": "c"},
                {"type": "tool_call", "task": task, "name": "apply_edit", "call_id": "d"},
            ]
        )
        _write_traces(tmp_path, events)

        records = []
        for i in range(4):
            records.append(
                AttemptRecord(
                    run_id=f"r{i}",
                    timestamp="2026-01-01T00:00:00Z",
                    item_type="finding",
                    item_id=f"finding:dead_code:src/file{i}.py",
                    category="dead_code",
                    complexity="",
                    approach=f"Fix {i}",
                    model="test",
                    retries=0,
                    outcome="success",
                    tokens_used=100,
                    duration_s=10.0,
                    failure_detail="",
                )
            )
        _write_attempts(tmp_path, records)

        items = [_make_finding(category="dead_code", file="src/utils.py")]
        result = mine_tool_patterns(tmp_path, items=items, max_per_category=5)

        assert "dead_code" in result
        assert result["dead_code"][0] == "read_file → apply_edit"

    def test_non_tool_call_events_ignored(self, tmp_path: Path) -> None:
        events = [
            {"type": "llm_response", "task": "dead-code-utils", "label": "engineer"},
            {"type": "tool_call", "task": "dead-code-utils", "name": "read_file", "call_id": "1"},
            {"type": "tool_result", "task": "dead-code-utils", "name": "read_file", "call_id": "1"},
            {"type": "tool_call", "task": "dead-code-utils", "name": "apply_edit", "call_id": "2"},
        ]
        _write_traces(tmp_path, events)

        records = [
            AttemptRecord(
                run_id="r1",
                timestamp="2026-01-01T00:00:00Z",
                item_type="finding",
                item_id="finding:dead_code:src/utils.py",
                category="dead_code",
                complexity="",
                approach="Fix",
                model="test",
                retries=0,
                outcome="success",
                tokens_used=100,
                duration_s=10.0,
                failure_detail="",
            ),
        ]
        _write_attempts(tmp_path, records)

        items = [_make_finding(category="dead_code", file="src/utils.py")]
        result = mine_tool_patterns(tmp_path, items=items)

        assert result["dead_code"][0] == "read_file → apply_edit"


class TestWriteToolPatterns:
    def test_write_new_patterns(self, tmp_path: Path) -> None:
        patterns = {"dead_code": ["read_file → apply_edit", "grep → create_file"]}
        result = write_tool_patterns(tmp_path, patterns)

        assert result is not None
        assert "patterns.md" in result

        content = Path(result).read_text()
        assert "## dead_code" in content
        assert "read_file → apply_edit" in content
        assert "grep → create_file" in content

    def test_merge_with_existing(self, tmp_path: Path) -> None:
        patterns_path = tmp_path / ".sigil" / "memory" / "patterns.md"
        patterns_path.parent.mkdir(parents=True, exist_ok=True)
        patterns_path.write_text(
            "# Tool Sequence Patterns by Category\n\n"
            "## dead_code\n\n"
            "- read_file → apply_edit\n\n"
            "## security\n\n"
            "- grep → read_file → apply_edit\n"
        )

        new_patterns = {"dead_code": ["grep → create_file"]}
        result = write_tool_patterns(tmp_path, new_patterns)

        assert result is not None
        content = Path(result).read_text()

        assert "grep → create_file" in content
        assert "read_file → apply_edit" in content
        assert "## security" in content

    def test_empty_patterns_returns_none(self, tmp_path: Path) -> None:
        result = write_tool_patterns(tmp_path, {})
        assert result is None

    def test_max_per_category_cap(self, tmp_path: Path) -> None:
        patterns_path = tmp_path / ".sigil" / "memory" / "patterns.md"
        patterns_path.parent.mkdir(parents=True, exist_ok=True)
        existing_lines = ["# Tool Sequence Patterns by Category\n", "\n", "## dead_code\n", "\n"]
        for i in range(10):
            existing_lines.append(f"- pattern_{i}\n")
        patterns_path.write_text("".join(existing_lines))

        new_patterns = {"dead_code": ["new_pattern"]}
        result = write_tool_patterns(tmp_path, new_patterns)

        content = Path(result).read_text()
        parsed = _parse_patterns_file(content)
        assert len(parsed["dead_code"]) <= 5
        assert "new_pattern" in parsed["dead_code"]


class TestFormatPatternHints:
    def test_existing_category(self) -> None:
        patterns = {"dead_code": ["read_file → apply_edit", "grep → create_file"]}
        result = format_pattern_hints(patterns, "dead_code")

        assert "dead_code" in result
        assert "read_file → apply_edit" in result
        assert "1." in result
        assert "2." in result

    def test_missing_category(self) -> None:
        patterns = {"dead_code": ["read_file → apply_edit"]}
        result = format_pattern_hints(patterns, "security")

        assert result == ""

    def test_empty_patterns(self) -> None:
        result = format_pattern_hints({}, "dead_code")
        assert result == ""


class TestLoadToolPatterns:
    def test_load_existing(self, tmp_path: Path) -> None:
        patterns_path = tmp_path / ".sigil" / "memory" / "patterns.md"
        patterns_path.parent.mkdir(parents=True, exist_ok=True)
        patterns_path.write_text(
            "# Tool Sequence Patterns by Category\n\n"
            "## dead_code\n\n"
            "- read_file → apply_edit\n\n"
            "## security\n\n"
            "- grep → read_file → apply_edit\n"
        )

        result = load_tool_patterns(tmp_path, "dead_code")
        assert "dead_code" in result
        assert "read_file → apply_edit" in result

    def test_missing_file(self, tmp_path: Path) -> None:
        result = load_tool_patterns(tmp_path, "dead_code")
        assert result == ""

    def test_missing_category(self, tmp_path: Path) -> None:
        patterns_path = tmp_path / ".sigil" / "memory" / "patterns.md"
        patterns_path.parent.mkdir(parents=True, exist_ok=True)
        patterns_path.write_text(
            "# Tool Sequence Patterns by Category\n\n## dead_code\n\n- read_file → apply_edit\n"
        )

        result = load_tool_patterns(tmp_path, "security")
        assert result == ""


class TestParsePatternsFile:
    def test_parse_well_formed(self) -> None:
        content = (
            "# Tool Sequence Patterns by Category\n\n"
            "## dead_code\n\n"
            "- read_file → apply_edit\n"
            "- grep → create_file\n\n"
            "## security\n\n"
            "- grep → read_file → apply_edit\n"
        )
        result = _parse_patterns_file(content)

        assert "dead_code" in result
        assert result["dead_code"] == ["read_file → apply_edit", "grep → create_file"]
        assert "security" in result
        assert result["security"] == ["grep → read_file → apply_edit"]

    def test_parse_empty(self) -> None:
        result = _parse_patterns_file("")
        assert result == {}

    def test_parse_no_patterns(self) -> None:
        content = "# Tool Sequence Patterns by Category\n"
        result = _parse_patterns_file(content)
        assert result == {}


class TestFormatPatternsContent:
    def test_format_roundtrip(self) -> None:
        patterns = {
            "dead_code": ["read_file → apply_edit", "grep → create_file"],
            "security": ["grep → read_file → apply_edit"],
        }
        content = _format_patterns_content(patterns)
        parsed = _parse_patterns_file(content)

        assert parsed["dead_code"] == patterns["dead_code"]
        assert parsed["security"] == patterns["security"]

    def test_sorted_categories(self) -> None:
        patterns = {
            "security": ["grep → apply_edit"],
            "dead_code": ["read_file → apply_edit"],
        }
        content = _format_patterns_content(patterns)

        dead_code_pos = content.index("## dead_code")
        security_pos = content.index("## security")
        assert dead_code_pos < security_pos
