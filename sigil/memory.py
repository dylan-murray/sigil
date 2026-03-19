from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sigil.config import SIGIL_DIR, MEMORY_DIR
from sigil.models import Component, RepoModel

REPO_MODEL_FILE = "repo-model.json"
FEATURES_FILE = "features.json"
FINDINGS_FILE = "findings.json"
RUNS_FILE = "runs.json"


@dataclass(slots=True)
class FeatureRecord:
    title: str
    description: str
    status: str  # "proposed" | "filed" | "implemented" | "rejected"
    pr_or_issue: str | None = None
    date: str = ""
    reason: str = ""


@dataclass(slots=True)
class FindingRecord:
    category: str
    file: str
    description: str
    status: str  # "fixed" | "filed" | "skipped"
    pr_or_issue: str | None = None
    date: str = ""


@dataclass(slots=True)
class RunRecord:
    timestamp: str
    model: str
    boldness: str
    discovery_mode: str  # "full" | "incremental" | "cached"
    findings_count: int = 0
    features_count: int = 0
    prs_opened: int = 0
    issues_filed: int = 0


@dataclass(slots=True)
class Memory:
    repo_model: RepoModel | None = None
    repo_model_timestamp: str = ""
    repo_model_head: str = ""
    features: list[FeatureRecord] = field(default_factory=list)
    findings: list[FindingRecord] = field(default_factory=list)
    runs: list[RunRecord] = field(default_factory=list)

    @property
    def has_repo_model(self) -> bool:
        return self.repo_model is not None

    def feature_titles(self) -> set[str]:
        return {f.title for f in self.features}

    def finding_keys(self) -> set[str]:
        return {f"{f.category}:{f.file}:{f.description}" for f in self.findings}

    def add_run(self, run: RunRecord) -> None:
        self.runs.append(run)

    def add_feature(self, feature: FeatureRecord) -> None:
        self.features.append(feature)

    def add_finding(self, finding: FindingRecord) -> None:
        self.findings.append(finding)


def _memory_dir(repo: Path) -> Path:
    return repo / SIGIL_DIR / MEMORY_DIR


def _serialize_repo_model(model: RepoModel) -> dict:
    return {
        "name": model.name,
        "language": model.language,
        "stack": model.stack,
        "purpose": model.purpose,
        "key_components": [
            {"name": c.name, "path": c.path, "description": c.description}
            for c in model.key_components
        ],
        "conventions": model.conventions,
        "test_command": model.test_command,
        "lint_command": model.lint_command,
        "build_command": model.build_command,
        "ci_provider": model.ci_provider,
        "open_issues_summary": model.open_issues_summary,
        "file_count": model.file_count,
        "top_level_dirs": model.top_level_dirs,
        "readme_snippet": model.readme_snippet,
        "claude_md_snippet": model.claude_md_snippet,
        "recent_commits": model.recent_commits,
    }


def _deserialize_repo_model(data: dict) -> RepoModel:
    components = [
        Component(name=c["name"], path=c["path"], description=c["description"])
        for c in data.get("key_components", [])
    ]
    return RepoModel(
        name=data["name"],
        language=data["language"],
        stack=data.get("stack", []),
        purpose=data.get("purpose", ""),
        key_components=components,
        conventions=data.get("conventions", []),
        test_command=data.get("test_command"),
        lint_command=data.get("lint_command"),
        build_command=data.get("build_command"),
        ci_provider=data.get("ci_provider"),
        open_issues_summary=data.get("open_issues_summary", ""),
        file_count=data.get("file_count", 0),
        top_level_dirs=data.get("top_level_dirs", []),
        readme_snippet=data.get("readme_snippet", ""),
        claude_md_snippet=data.get("claude_md_snippet", ""),
        recent_commits=data.get("recent_commits", []),
    )


def _read_json(path: Path) -> dict | list:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def load(repo: Path) -> Memory:
    mdir = _memory_dir(repo)
    if not mdir.exists():
        return Memory()

    repo_data = _read_json(mdir / REPO_MODEL_FILE)
    features_data = _read_json(mdir / FEATURES_FILE)
    findings_data = _read_json(mdir / FINDINGS_FILE)
    runs_data = _read_json(mdir / RUNS_FILE)

    repo_model = None
    repo_model_timestamp = ""
    repo_model_head = ""
    if repo_data and "model" in repo_data:
        repo_model = _deserialize_repo_model(repo_data["model"])
        repo_model_timestamp = repo_data.get("timestamp", "")
        repo_model_head = repo_data.get("head", "")

    features = [
        FeatureRecord(**f)
        for f in (features_data.get("features", []) if isinstance(features_data, dict) else [])
    ]
    findings = [
        FindingRecord(**f)
        for f in (findings_data.get("findings", []) if isinstance(findings_data, dict) else [])
    ]
    runs = [
        RunRecord(**r) for r in (runs_data.get("runs", []) if isinstance(runs_data, dict) else [])
    ]

    return Memory(
        repo_model=repo_model,
        repo_model_timestamp=repo_model_timestamp,
        repo_model_head=repo_model_head,
        features=features,
        findings=findings,
        runs=runs,
    )


def save(repo: Path, memory: Memory) -> None:
    mdir = _memory_dir(repo)
    mdir.mkdir(parents=True, exist_ok=True)

    if memory.repo_model:
        repo_data = {
            "timestamp": memory.repo_model_timestamp or _now(),
            "head": memory.repo_model_head,
            "model": _serialize_repo_model(memory.repo_model),
        }
        (mdir / REPO_MODEL_FILE).write_text(json.dumps(repo_data, indent=2))

    features_data = {
        "features": [
            {
                "title": f.title,
                "description": f.description,
                "status": f.status,
                "pr_or_issue": f.pr_or_issue,
                "date": f.date,
                "reason": f.reason,
            }
            for f in memory.features
        ]
    }
    (mdir / FEATURES_FILE).write_text(json.dumps(features_data, indent=2))

    findings_data = {
        "findings": [
            {
                "category": f.category,
                "file": f.file,
                "description": f.description,
                "status": f.status,
                "pr_or_issue": f.pr_or_issue,
                "date": f.date,
            }
            for f in memory.findings
        ]
    }
    (mdir / FINDINGS_FILE).write_text(json.dumps(findings_data, indent=2))

    runs_data = {
        "runs": [
            {
                "timestamp": r.timestamp,
                "model": r.model,
                "boldness": r.boldness,
                "discovery_mode": r.discovery_mode,
                "findings_count": r.findings_count,
                "features_count": r.features_count,
                "prs_opened": r.prs_opened,
                "issues_filed": r.issues_filed,
            }
            for r in memory.runs
        ]
    }
    (mdir / RUNS_FILE).write_text(json.dumps(runs_data, indent=2))


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
