import pytest
from pydantic import ValidationError

from sigil.core.tool_schemas import ApplyEditArgs, CreateFileArgs, MultiEditArgs


@pytest.mark.parametrize(
    "args, expected_loc",
    [
        ({"file": "a.py", "new_content": "x"}, "old_content"),
        ({"file": "a.py", "old_content": "x"}, "new_content"),
        ({"file": "", "old_content": "a", "new_content": "b"}, "file"),
        ({"file": "a\nb.py", "old_content": "a", "new_content": "b"}, "file"),
        ({"file": "a\rb.py", "old_content": "a", "new_content": "b"}, "file"),
        ({"file": "a\tb.py", "old_content": "a", "new_content": "b"}, "file"),
        ({"file": "limit>100", "old_content": "a", "new_content": "b"}, "file"),
        ({"file": "a<b.py", "old_content": "a", "new_content": "b"}, "file"),
        (
            {"file": "a.py", "old_content": "a", "new_content": "b", "limit": 100},
            "limit",
        ),
    ],
)
def test_apply_edit_rejects_bad(args, expected_loc):
    with pytest.raises(ValidationError) as exc_info:
        ApplyEditArgs.model_validate(args)
    locs = [".".join(str(p) for p in e["loc"]) for e in exc_info.value.errors()]
    assert any(expected_loc in loc for loc in locs), f"expected {expected_loc} in {locs}"


def test_multi_edit_rejects_empty_edits():
    with pytest.raises(ValidationError) as exc_info:
        MultiEditArgs.model_validate({"file": "a.py", "edits": []})
    locs = [".".join(str(p) for p in e["loc"]) for e in exc_info.value.errors()]
    assert any("edits" in loc for loc in locs)


@pytest.mark.parametrize(
    "args, expected_loc",
    [
        ({"content": "x"}, "file"),
        ({"file": "a.py"}, "content"),
        ({"file": "bad>name.py", "content": "x"}, "file"),
        ({"file": "a.py", "content": "x", "mode": "0644"}, "mode"),
    ],
)
def test_create_file_rejects_bad(args, expected_loc):
    with pytest.raises(ValidationError) as exc_info:
        CreateFileArgs.model_validate(args)
    locs = [".".join(str(p) for p in e["loc"]) for e in exc_info.value.errors()]
    assert any(expected_loc in loc for loc in locs), f"expected {expected_loc} in {locs}"
