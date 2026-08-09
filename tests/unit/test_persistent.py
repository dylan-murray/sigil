import json

from sigil.state.persistent import (
    PersistentState,
    add_lesson,
    load_persistent_state,
    record_failure,
    record_veto,
    save_persistent_state,
)


def _state_dir(tmp_path):
    return tmp_path / ".sigil" / "memory"


def test_load_persistent_state_returns_default_when_missing(tmp_path):
    state = load_persistent_state(tmp_path)
    assert state.vetoed_fingerprints == set()
    assert state.failed_patterns == {}
    assert state.lessons == []


def test_load_persistent_state_returns_default_on_corrupt_file(tmp_path):
    d = _state_dir(tmp_path)
    d.mkdir(parents=True)
    (d / "persistent.json").write_text("not valid json {{{")
    state = load_persistent_state(tmp_path)
    assert state.vetoed_fingerprints == set()
    assert state.failed_patterns == {}
    assert state.lessons == []


def test_save_and_load_roundtrip(tmp_path):
    state = PersistentState(
        vetoed_fingerprints={"finding:dead_code:foo.py"},
        failed_patterns={"dead_code:post_hook": 3},
        lessons=["Avoid editing generated files"],
    )
    path = save_persistent_state(tmp_path, state)
    assert path.exists()

    loaded = load_persistent_state(tmp_path)
    assert loaded.vetoed_fingerprints == {"finding:dead_code:foo.py"}
    assert loaded.failed_patterns == {"dead_code:post_hook": 3}
    assert loaded.lessons == ["Avoid editing generated files"]


def test_record_veto_adds_fingerprints(tmp_path):
    record_veto(tmp_path, ["finding:dead_code:foo.py", "idea:add-caching"])
    state = load_persistent_state(tmp_path)
    assert "finding:dead_code:foo.py" in state.vetoed_fingerprints
    assert "idea:add-caching" in state.vetoed_fingerprints


def test_record_veto_is_idempotent(tmp_path):
    record_veto(tmp_path, ["finding:dead_code:foo.py"])
    record_veto(tmp_path, ["finding:dead_code:foo.py"])
    state = load_persistent_state(tmp_path)
    assert len([fp for fp in state.vetoed_fingerprints if fp == "finding:dead_code:foo.py"]) == 1


def test_record_veto_merges_with_existing(tmp_path):
    record_veto(tmp_path, ["finding:dead_code:foo.py"])
    record_veto(tmp_path, ["idea:add-caching"])
    state = load_persistent_state(tmp_path)
    assert state.vetoed_fingerprints == {"finding:dead_code:foo.py", "idea:add-caching"}


def test_record_failure_increments_count(tmp_path):
    record_failure(tmp_path, "dead_code:post_hook")
    state = load_persistent_state(tmp_path)
    assert state.failed_patterns == {"dead_code:post_hook": 1}

    record_failure(tmp_path, "dead_code:post_hook")
    state = load_persistent_state(tmp_path)
    assert state.failed_patterns == {"dead_code:post_hook": 2}


def test_record_failure_tracks_multiple_patterns(tmp_path):
    record_failure(tmp_path, "dead_code:post_hook")
    record_failure(tmp_path, "security:no_changes")
    state = load_persistent_state(tmp_path)
    assert state.failed_patterns == {"dead_code:post_hook": 1, "security:no_changes": 1}


def test_add_lesson_appends(tmp_path):
    add_lesson(tmp_path, "Avoid editing generated files")
    state = load_persistent_state(tmp_path)
    assert state.lessons == ["Avoid editing generated files"]

    add_lesson(tmp_path, "Always run tests before committing")
    state = load_persistent_state(tmp_path)
    assert state.lessons == [
        "Avoid editing generated files",
        "Always run tests before committing",
    ]


def test_add_lesson_deduplicates(tmp_path):
    add_lesson(tmp_path, "Avoid editing generated files")
    add_lesson(tmp_path, "Avoid editing generated files")
    state = load_persistent_state(tmp_path)
    assert state.lessons == ["Avoid editing generated files"]


def test_persistent_state_json_format(tmp_path):
    state = PersistentState(
        vetoed_fingerprints={"a", "b"},
        failed_patterns={"x": 1},
        lessons=["lesson1"],
    )
    save_persistent_state(tmp_path, state)

    d = _state_dir(tmp_path)
    raw = json.loads((d / "persistent.json").read_text())
    assert isinstance(raw["vetoed_fingerprints"], list)
    assert isinstance(raw["failed_patterns"], dict)
    assert isinstance(raw["lessons"], list)
