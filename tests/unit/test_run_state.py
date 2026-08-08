import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from sigil.core.config import CONFIG_FILE, SIGIL_DIR
from sigil.state.run_state import (
    RunState,
    compute_state_hash,
    load_last_run_state,
    save_run_state,
)


@pytest.fixture()
def repo(tmp_path):
    sigil_dir = tmp_path / SIGIL_DIR
    sigil_dir.mkdir(parents=True)
    (sigil_dir / CONFIG_FILE).write_text("model: test-model\n")
    return tmp_path


async def test_compute_state_hash_deterministic(repo):
    with patch("sigil.state.run_state.get_head", new_callable=AsyncMock, return_value="abc123"):
        hash1 = await compute_state_hash(repo)
        hash2 = await compute_state_hash(repo)
    assert hash1 == hash2
    assert len(hash1) == 64


async def test_compute_state_hash_different_head(repo):
    with patch("sigil.state.run_state.get_head", new_callable=AsyncMock, return_value="abc123"):
        hash1 = await compute_state_hash(repo)
    with patch("sigil.state.run_state.get_head", new_callable=AsyncMock, return_value="def456"):
        hash2 = await compute_state_hash(repo)
    assert hash1 != hash2


async def test_compute_state_hash_different_config(repo):
    with patch("sigil.state.run_state.get_head", new_callable=AsyncMock, return_value="abc123"):
        hash1 = await compute_state_hash(repo)
    (repo / SIGIL_DIR / CONFIG_FILE).write_text("model: different-model\n")
    with patch("sigil.state.run_state.get_head", new_callable=AsyncMock, return_value="abc123"):
        hash2 = await compute_state_hash(repo)
    assert hash1 != hash2


async def test_compute_state_hash_empty_head(repo):
    with patch("sigil.state.run_state.get_head", new_callable=AsyncMock, return_value=""):
        result = await compute_state_hash(repo)
    assert len(result) == 64


async def test_compute_state_hash_missing_config(tmp_path):
    sigil_dir = tmp_path / SIGIL_DIR
    sigil_dir.mkdir(parents=True)
    with patch("sigil.state.run_state.get_head", new_callable=AsyncMock, return_value="abc123"):
        result = await compute_state_hash(tmp_path)
    assert len(result) == 64


def test_load_last_run_state_missing_file(repo):
    result = load_last_run_state(repo)
    assert result is None


def test_load_last_run_state_valid_json(repo):
    state = RunState(state_hash="abc123def456", had_failures=False)
    save_run_state(repo, state)
    loaded = load_last_run_state(repo)
    assert loaded is not None
    assert loaded.state_hash == "abc123def456"
    assert loaded.had_failures is False


def test_load_last_run_state_invalid_json(repo):
    path = repo / SIGIL_DIR / "last-run-state.json"
    path.write_text("not valid json{{{")
    result = load_last_run_state(repo)
    assert result is None


def test_load_last_run_state_missing_keys(repo):
    path = repo / SIGIL_DIR / "last-run-state.json"
    path.write_text(json.dumps({"state_hash": "abc"}))
    result = load_last_run_state(repo)
    assert result is None


def test_load_last_run_state_wrong_types(repo):
    path = repo / SIGIL_DIR / "last-run-state.json"
    path.write_text(json.dumps({"state_hash": "abc", "had_failures": "not_a_bool"}))
    result = load_last_run_state(repo)
    assert result is None


def test_save_run_state_creates_directory(tmp_path):
    repo = tmp_path / "new_repo"
    repo.mkdir()
    state = RunState(state_hash="abc", had_failures=True)
    save_run_state(repo, state)
    loaded = load_last_run_state(repo)
    assert loaded is not None
    assert loaded.state_hash == "abc"
    assert loaded.had_failures is True


def test_save_and_load_roundtrip(repo):
    state = RunState(state_hash="sha256hash" * 4, had_failures=False)
    save_run_state(repo, state)
    loaded = load_last_run_state(repo)
    assert loaded == state


def test_save_overwrites_existing(repo):
    state1 = RunState(state_hash="hash1", had_failures=False)
    save_run_state(repo, state1)
    state2 = RunState(state_hash="hash2", had_failures=True)
    save_run_state(repo, state2)
    loaded = load_last_run_state(repo)
    assert loaded is not None
    assert loaded.state_hash == "hash2"
    assert loaded.had_failures is True