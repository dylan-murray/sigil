# pytest + pytest-asyncio Test Setup with Mock Patterns

## Unit Tests (`tests/unit/`)

### Config Validation Tests

Test the new list-based agent config format:

```python
def test_instances_for_with_entries():
    config = Config(
        model="default/model",
        agents={
            "ideator": [
                {"model": "m1"},
                {"model": "m2", "reasoning_effort": "high", "max_tokens": 8000},
            ]
        },
    )
    instances = config.instances_for("ideator")
    assert [i.model for i in instances] == ["m1", "m2"]
```

Test validation errors:
- Agent value not a list → `ValueError`
- Empty agent list → `ValueError`
- Entry not a mapping → `ValueError`
- Unknown key in entry → `ValueError`
- Invalid `reasoning_effort` → `ValueError`
- Unknown agent name → `ValueError`
- Unknown top-level field (e.g. `arbiter`) → `ValueError`

### Ideation Tests

Test multi-instance parallel ideation:

```python
async def test_ideate_runs_multiple_ideators_in_parallel(tmp_path, monkeypatch):
    config = Config(
        model="default-model",
        agents={"ideator": [{"model": "model-a"}, {"model": "model-b"}]},
    )
    ideas = await ideate(tmp_path, config)
    assert set(models_seen) == {"model-a", "model-b"}
```

Test that temperature is now a single value per boldness level (not a range):

```python
@pytest.mark.parametrize(
    "boldness,expected_temp",
    [
        ("balanced", TEMP_BY_BOLDNESS["balanced"]),
        ("bold", TEMP_BY_BOLDNESS["bold"]),
        ("experimental", TEMP_BY_BOLDNESS["experimental"]),
    ],
)
async def test_ideate_uses_boldness_temperature(tmp_path, monkeypatch, boldness, expected_temp):
    ...
```

### Tool Tests

Test normalized fuzzy matching in `apply_edit`:

```python
@pytest.mark.parametrize(
    "file_text,old_text",
    [
        ("msg = 'hello'\n", "msg = \u2018hello\u2019"),
        ('msg = "hello"\n', "msg = \u201chello\u201d"),
        ("a - b\n", "a \u2014 b"),
        ("x = 1\n", "x\u00a0=\u00a01"),
    ],
    ids=["smart_single", "smart_double", "em_dash", "nbsp"],
)
async def test_apply_edit_normalized_match(tmp_path, file_text, old_text):
    ...
```

Test atomic multi_edit:
- Adjacent line edits work
- Overlapping edits rejected
- Reverse position order preserves offsets
- Normalized fallback works
- Partial failure reports each failure
- Ambiguous matches reported
- No-op edits detected (both `apply_edit` and `multi_edit`)

Test oversized first line in pagination:

```python
def test_paginate_lines_first_line_too_big():
    big = "x" * (MAX_READ_BYTES + 100) + "\n"
    result = paginate_lines([big, "small\n"], offset=1, file_path="huge.json")
    assert "Line 1 alone is" in result
    assert "sed -n '1p' huge.json" in result
```

### Validation Tests

Validation tests simplified — no parallel/arbiter tests:
- `test_apply_decisions_propagates_relevant_files`
- `test_validate_all_captures_relevant_files`
- `_find_disagreements` tests removed (function removed)
- `test_parallel_reviewers_agree` removed
- `test_parallel_disagree_runs_arbiter` removed
- `test_parallel_arbiter_fallback_to_veto` removed
- `test_parallel_rebalances_priorities_*` removed

### Agent Tests

Test that `reduce_context` is NOT called unconditionally:

```python
async def test_reduce_context_not_called_below_pressure(monkeypatch):
    ...
    assert reduce_calls == [], (
        "reduce_context must not run below pressure"
    )
```

### GitHub Dedup Tests

Test the new HTML marker-based dedup system:

```python
async def test_dedup_items_filters_duplicates():
    client = _mock_client()

    mock_pr = MagicMock()
    mock_pr.title = "sigil: drop unreachable cleanup branch"
    mock_pr.body = (
        "## Changes\nDropped dead branch.\n\n"
        "---\n*Automated by [Sigil]*\n"
        "<!-- sigil-key: dead_code:src/utils.py -->"
    )
    mock_label = MagicMock()
    mock_label.name = SIGIL_LABEL
    mock_pr.labels = [mock_label]
    ...
```

### Utils Tests

Test `normalize_for_fuzzy_match`:

```python
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("\u2018hello\u2019", "'hello'"),
        ("\u201chello\u201d", '"hello"'),
        ("a\u2014b", "a-b"),
        ("a\u00a0b", "a b"),
    ],
)
def test_normalize_character_classes(raw, expected):
    assert normalize_for_fuzzy_match(raw) == expected
```

## Integration Tests (`tests/integration/`)

Integration tests use the full pipeline with mocked LLM responses. They test end-to-end flows including worktree creation, tool execution, and GitHub publishing.
