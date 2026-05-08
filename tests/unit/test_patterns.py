from sigil.state.patterns import (
    MAX_PATTERNS_PER_CATEGORY,
    extract_tool_sequence,
    get_pattern_hints,
    load_patterns,
    normalize_sequence,
    record_pattern,
    save_patterns,
)


def test_extract_tool_sequence_from_messages():
    messages = [
        {"role": "user", "content": "implement feature"},
        {
            "role": "assistant",
            "tool_calls": [
                {"function": {"name": "read_file"}, "id": "call_1"},
            ],
        },
        {"role": "tool", "content": "file contents", "tool_call_id": "call_1"},
        {
            "role": "assistant",
            "tool_calls": [
                {"function": {"name": "grep"}, "id": "call_2"},
                {"function": {"name": "read_file"}, "id": "call_3"},
            ],
        },
        {"role": "tool", "content": "grep results", "tool_call_id": "call_2"},
        {
            "role": "assistant",
            "tool_calls": [
                {"function": {"name": "apply_edit"}, "id": "call_4"},
            ],
        },
    ]
    result = extract_tool_sequence(messages)
    assert result == ["read_file", "grep", "read_file", "apply_edit"]


def test_extract_tool_sequence_object_format():
    from unittest.mock import MagicMock

    func = MagicMock()
    func.name = "read_file"
    tc = MagicMock()
    tc.function = func

    messages = [
        {"role": "assistant", "tool_calls": [tc]},
    ]
    result = extract_tool_sequence(messages)
    assert result == ["read_file"]


def test_extract_tool_sequence_empty_messages():
    assert extract_tool_sequence([]) == []


def test_extract_tool_sequence_no_tool_calls():
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "I will help you."},
    ]
    assert extract_tool_sequence(messages) == []


def test_extract_tool_sequence_skips_empty_names():
    messages = [
        {
            "role": "assistant",
            "tool_calls": [
                {"function": {"name": "read_file"}, "id": "call_1"},
                {"function": {"name": ""}, "id": "call_2"},
                {"function": {"name": "apply_edit"}, "id": "call_3"},
            ],
        },
    ]
    result = extract_tool_sequence(messages)
    assert result == ["read_file", "apply_edit"]


def test_normalize_sequence_collapses_consecutive_duplicates():
    assert normalize_sequence(["read_file", "read_file", "grep", "grep", "apply_edit"]) == [
        "read_file",
        "grep",
        "apply_edit",
    ]


def test_normalize_sequence_empty():
    assert normalize_sequence([]) == []


def test_normalize_sequence_single():
    assert normalize_sequence(["read_file"]) == ["read_file"]


def test_normalize_sequence_no_duplicates():
    assert normalize_sequence(["read_file", "grep", "apply_edit"]) == [
        "read_file",
        "grep",
        "apply_edit",
    ]


def test_normalize_sequence_all_same():
    assert normalize_sequence(["read_file", "read_file", "read_file"]) == ["read_file"]


def test_record_pattern_new_category(tmp_path):
    record_pattern(tmp_path, "dead_code", ["read_file", "grep", "apply_edit"])
    patterns = load_patterns(tmp_path)
    assert "dead_code" in patterns
    assert len(patterns["dead_code"]) == 1
    assert patterns["dead_code"][0]["sequence"] == "read_file → grep → apply_edit"
    assert patterns["dead_code"][0]["count"] == 1


def test_record_pattern_existing_sequence_increments_count(tmp_path):
    record_pattern(tmp_path, "dead_code", ["read_file", "apply_edit"])
    record_pattern(tmp_path, "dead_code", ["read_file", "apply_edit"])
    patterns = load_patterns(tmp_path)
    assert len(patterns["dead_code"]) == 1
    assert patterns["dead_code"][0]["count"] == 2


def test_record_pattern_different_sequences_same_category(tmp_path):
    record_pattern(tmp_path, "dead_code", ["read_file", "apply_edit"])
    record_pattern(tmp_path, "dead_code", ["grep", "apply_edit"])
    patterns = load_patterns(tmp_path)
    assert len(patterns["dead_code"]) == 2


def test_record_pattern_top_k_limit(tmp_path):
    for i in range(MAX_PATTERNS_PER_CATEGORY + 3):
        seq = [f"tool_{i}"]
        for _ in range(MAX_PATTERNS_PER_CATEGORY + 3 - i):
            record_pattern(tmp_path, "types", seq)
    patterns = load_patterns(tmp_path)
    assert len(patterns["types"]) == MAX_PATTERNS_PER_CATEGORY
    assert patterns["types"][0]["count"] >= patterns["types"][1]["count"]


def test_record_pattern_empty_sequence(tmp_path):
    record_pattern(tmp_path, "dead_code", [])
    patterns = load_patterns(tmp_path)
    assert "dead_code" not in patterns


def test_record_pattern_empty_category(tmp_path):
    record_pattern(tmp_path, "", ["read_file"])
    patterns = load_patterns(tmp_path)
    assert patterns == {}


def test_record_pattern_concurrent_write_safety(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("disk full")

    record_pattern(tmp_path, "dead_code", ["read_file", "apply_edit"])
    monkeypatch.setattr("sigil.state.patterns.save_patterns", boom)
    record_pattern(tmp_path, "dead_code", ["grep", "apply_edit"])


def test_get_pattern_hints_with_patterns(tmp_path):
    record_pattern(tmp_path, "dead_code", ["read_file", "apply_edit"])
    record_pattern(tmp_path, "dead_code", ["read_file", "apply_edit"])
    record_pattern(tmp_path, "dead_code", ["grep", "apply_edit"])
    hints = get_pattern_hints(tmp_path, "dead_code")
    assert "## Learned Tool Patterns" in hints
    assert "read_file → apply_edit" in hints
    assert "2 successes" in hints
    assert "grep → apply_edit" in hints
    assert "1 success" in hints


def test_get_pattern_hints_no_patterns(tmp_path):
    assert get_pattern_hints(tmp_path, "dead_code") == ""


def test_get_pattern_hints_unknown_category(tmp_path):
    record_pattern(tmp_path, "dead_code", ["read_file", "apply_edit"])
    assert get_pattern_hints(tmp_path, "security") == ""


def test_load_patterns_corrupt_file(tmp_path):
    path = tmp_path / ".sigil" / "patterns.json"
    path.parent.mkdir(parents=True)
    path.write_text("NOT VALID JSON{{{")
    assert load_patterns(tmp_path) == {}


def test_load_patterns_missing_file(tmp_path):
    assert load_patterns(tmp_path) == {}


def test_save_and_load_roundtrip(tmp_path):
    patterns = {
        "dead_code": [
            {"sequence": "read_file → apply_edit", "count": 3, "last_seen": "2026-01-01T00:00:00Z"}
        ]
    }
    save_patterns(tmp_path, patterns)
    loaded = load_patterns(tmp_path)
    assert loaded == patterns


def test_save_patterns_creates_directory(tmp_path):
    sigil_dir = tmp_path / ".sigil"
    assert not sigil_dir.exists()
    save_patterns(tmp_path, {})
    assert sigil_dir.exists()
    assert (sigil_dir / "patterns.json").exists()
