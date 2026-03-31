from pathlib import Path
from unittest.mock import patch

from sigil.state.memory import append_veto, is_vetoed, load_veto_list


def test_append_veto_creates_veto_list(tmp_path: Path) -> None:
    repo = tmp_path

    result = append_veto(repo, "Avoid large cross-session state machines")

    assert result.endswith("working.md")
    content = (repo / ".sigil" / "memory" / "working.md").read_text()
    assert "## VETO_LIST" in content
    assert "- Avoid large cross-session state machines" in content
    assert load_veto_list(repo) == ["Avoid large cross-session state machines"]


def test_append_veto_deduplicates_normalized_reason(tmp_path: Path) -> None:
    repo = tmp_path
    working = repo / ".sigil" / "memory"
    working.mkdir(parents=True)
    (working / "working.md").write_text("## VETO_LIST\n\n- Reject complex state management\n")

    append_veto(repo, "sigil: reject complex state management")

    content = (working / "working.md").read_text()
    assert content.count("Reject complex state management") == 1


@patch("sigil.state.memory.load_veto_list", return_value=["Reject complex state management"])
def test_is_vetoed_matches_similar_text(mock_load_veto_list: object, tmp_path: Path) -> None:
    assert is_vetoed(tmp_path, "Sigil: reject complex state management")
    assert not is_vetoed(tmp_path, "Add retry logic")
