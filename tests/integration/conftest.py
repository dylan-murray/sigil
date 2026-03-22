import os
import subprocess
from pathlib import Path

import pytest

from sigil.config import Config

PROVIDERS = {
    "openai": {
        "env_vars": ["OPENAI_API_KEY"],
        "model": "openai/gpt-4o-mini",
    },
    "anthropic": {
        "env_vars": ["ANTHROPIC_API_KEY"],
        "model": "anthropic/claude-haiku-4-5-20251001",
    },
    "gemini": {
        "env_vars": ["GEMINI_API_KEY"],
        "model": "gemini/gemini-2.0-flash",
    },
    "bedrock": {
        "env_vars": ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION_NAME"],
        "model": "bedrock/anthropic.claude-3-haiku-20240307-v1:0",
    },
    "azure": {
        "env_vars": ["AZURE_API_KEY", "AZURE_API_BASE"],
        "model": "azure/gpt-4o-mini",
    },
    "mistral": {
        "env_vars": ["MISTRAL_API_KEY"],
        "model": "mistral/mistral-small-latest",
    },
}

PROVIDER_IDS = list(PROVIDERS.keys())


def skip_if_no_key(provider: str) -> None:
    info = PROVIDERS[provider]
    for var in info["env_vars"]:
        if not os.environ.get(var):
            pytest.skip(f"{var} not set")


def model_for(provider: str) -> str:
    return PROVIDERS[provider]["model"]


def make_config(provider: str, **overrides: object) -> Config:
    defaults = {
        "model": model_for(provider),
        "boldness": "bold",
        "max_ideas_per_run": 3,
        "lint_cmd": None,
        "test_cmd": None,
    }
    defaults.update(overrides)
    return Config(**defaults)


def _git_init(repo: Path) -> None:
    for cmd in [
        ["git", "init"],
        ["git", "config", "user.email", "test@test.com"],
        ["git", "config", "user.name", "Test"],
        ["git", "add", "."],
        ["git", "commit", "-m", "initial"],
    ]:
        subprocess.run(cmd, cwd=repo, capture_output=True, check=True)


SAMPLE_APP = """\
import os

DB_PASSWORD = "hunter2"


def add(a, b):
    return a - b


def multiply(x, y):
    result = x * y
    return result


def unused_helper():
    pass


def fetch_data(url):
    import urllib.request

    resp = urllib.request.urlopen(url)
    return resp.read()
"""

SAMPLE_README = """\
# Sample App

A sample application.
"""


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "sample"
    repo.mkdir()
    (repo / ".sigil").mkdir()
    (repo / "app.py").write_text(SAMPLE_APP)
    (repo / "README.md").write_text(SAMPLE_README)
    _git_init(repo)
    return repo


@pytest.fixture
def tiny_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("def add(a, b):\n    return a - b\n")
    _git_init(repo)
    return repo
