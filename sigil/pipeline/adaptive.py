import json
import logging
from dataclasses import dataclass
from pathlib import Path

from sigil.core.config import SIGIL_DIR, Config
from sigil.core.utils import arun, get_head
from sigil.pipeline.models import Finding

logger = logging.getLogger(__name__)

RUN_STATE_FILE = "run_state.json"
FINDINGS_FILE = "findings.json"

DOC_EXTENSIONS = frozenset({".md", ".rst", ".txt", ".adoc", ".org"})
CONFIG_EXTENSIONS = frozenset({".yml", ".yaml", ".toml", ".ini", ".cfg", ".env"})
CONFIG_NAMES = frozenset(
    {
        "Makefile",
        "Dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        ".env",
        ".env.local",
        ".env.production",
        ".env.development",
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "tox.ini",
        "ruff.toml",
        ".flake8",
        ".isort.cfg",
        "mypy.ini",
        ".mypy.ini",
        "tsconfig.json",
        "package.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "Gemfile",
        "Cargo.toml",
        "go.mod",
        "go.sum",
    }
)
CODE_EXTENSIONS = frozenset(
    {
        ".py",
        ".pyi",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".go",
        ".rs",
        ".rb",
        ".java",
        ".kt",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".cs",
        ".swift",
        ".sh",
        ".bash",
        ".zsh",
    }
)


@dataclass(frozen=True, slots=True)
class RunState:
    last_head: str
    last_run_time: str


@dataclass(frozen=True, slots=True)
class StageDecision:
    stage: str
    skip: bool
    rationale: str


@dataclass(frozen=True, slots=True)
class AdaptivePlan:
    decisions: list[StageDecision]
    changed_files: list[str]
    last_run_head: str | None
    current_head: str

    def should_skip(self, stage: str) -> bool:
        for d in self.decisions:
            if d.stage == stage:
                return d.skip
        return False

    def rationale_for(self, stage: str) -> str | None:
        for d in self.decisions:
            if d.stage == stage:
                return d.rationale
        return None


def classify_file(path: str) -> str:
    from pathlib import PurePosixPath

    p = PurePosixPath(path)
    name = p.name
    ext = p.suffix.lower()

    if name in CONFIG_NAMES or ext in CONFIG_EXTENSIONS:
        return "config"
    if ext in DOC_EXTENSIONS:
        return "docs"
    if ext in CODE_EXTENSIONS or ext == "":
        return "code"
    return "code"


async def compute_adaptive_plan(
    repo: Path,
    config: Config,
    force_all: bool = False,
) -> AdaptivePlan:
    if force_all or not config.adaptive_stages:
        current_head = await get_head(repo)
        return AdaptivePlan(
            decisions=[],
            changed_files=[],
            last_run_head=None,
            current_head=current_head or "",
        )

    run_state = load_run_state(repo)
    if run_state is None:
        current_head = await get_head(repo)
        return AdaptivePlan(
            decisions=[],
            changed_files=[],
            last_run_head=None,
            current_head=current_head or "",
        )

    current_head = await get_head(repo)
    if not current_head:
        return AdaptivePlan(
            decisions=[],
            changed_files=[],
            last_run_head=run_state.last_head,
            current_head="",
        )

    rc, stdout, _ = await arun(
        ["git", "diff", "--name-only", f"{run_state.last_head}..{current_head}"],
        cwd=repo,
        timeout=30,
    )

    if rc != 0:
        rc2, stdout2, _ = await arun(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=repo,
            timeout=30,
        )
        if rc2 == 0:
            changed = [line for line in stdout2.strip().splitlines() if line.strip()]
        else:
            return AdaptivePlan(
                decisions=[],
                changed_files=[],
                last_run_head=run_state.last_head,
                current_head=current_head,
            )
    else:
        changed = [line for line in stdout.strip().splitlines() if line.strip()]

    classifications: dict[str, list[str]] = {"docs": [], "config": [], "code": []}
    for f in changed:
        cat = classify_file(f)
        classifications[cat].append(f)

    decisions: list[StageDecision] = []

    if not changed:
        decisions.append(
            StageDecision(
                stage="discovery",
                skip=True,
                rationale="No files changed since last run",
            )
        )
        decisions.append(
            StageDecision(
                stage="analysis",
                skip=True,
                rationale="No files changed since last run",
            )
        )
        decisions.append(
            StageDecision(
                stage="ideation",
                skip=False,
                rationale="Ideation runs regardless of changes",
            )
        )
    elif classifications["code"] or (classifications["docs"] and classifications["config"]):
        decisions.append(
            StageDecision(
                stage="discovery",
                skip=False,
                rationale="Code or mixed changes detected",
            )
        )
        decisions.append(
            StageDecision(
                stage="analysis",
                skip=False,
                rationale="Code or mixed changes detected",
            )
        )
        decisions.append(
            StageDecision(
                stage="ideation",
                skip=False,
                rationale="Ideation runs regardless of changes",
            )
        )
    elif classifications["docs"] and not classifications["config"] and not classifications["code"]:
        decisions.append(
            StageDecision(
                stage="discovery",
                skip=False,
                rationale="Docs-only changes — discovery still needed for context",
            )
        )
        decisions.append(
            StageDecision(
                stage="analysis",
                skip=True,
                rationale="Only docs changed — no code analysis needed",
            )
        )
        decisions.append(
            StageDecision(
                stage="ideation",
                skip=False,
                rationale="Ideation runs regardless of changes",
            )
        )
    elif classifications["config"] and not classifications["code"] and not classifications["docs"]:
        decisions.append(
            StageDecision(
                stage="discovery",
                skip=False,
                rationale="Config changes — discovery still needed for context",
            )
        )
        decisions.append(
            StageDecision(
                stage="analysis",
                skip=True,
                rationale="Only config changed — no code analysis needed",
            )
        )
        decisions.append(
            StageDecision(
                stage="ideation",
                skip=True,
                rationale="Only config changed — no new ideas needed",
            )
        )
    else:
        decisions.append(
            StageDecision(
                stage="discovery",
                skip=False,
                rationale="Changes detected",
            )
        )
        decisions.append(
            StageDecision(
                stage="analysis",
                skip=False,
                rationale="Changes detected",
            )
        )
        decisions.append(
            StageDecision(
                stage="ideation",
                skip=False,
                rationale="Ideation runs regardless of changes",
            )
        )

    return AdaptivePlan(
        decisions=decisions,
        changed_files=changed,
        last_run_head=run_state.last_head,
        current_head=current_head,
    )


def load_run_state(repo: Path) -> RunState | None:
    path = repo / SIGIL_DIR / RUN_STATE_FILE
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return RunState(last_head=data["last_head"], last_run_time=data["last_run_time"])
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def save_run_state(repo: Path, state: RunState) -> None:
    sigil_dir = repo / SIGIL_DIR
    sigil_dir.mkdir(parents=True, exist_ok=True)
    path = sigil_dir / RUN_STATE_FILE
    path.write_text(
        json.dumps({"last_head": state.last_head, "last_run_time": state.last_run_time}, indent=2)
    )


def load_previous_findings(repo: Path) -> list[Finding]:
    path = repo / SIGIL_DIR / FINDINGS_FILE
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        return [
            Finding(
                category=f["category"],
                file=f["file"],
                line=f.get("line"),
                description=f["description"],
                risk=f["risk"],
                suggested_fix=f["suggested_fix"],
                disposition=f["disposition"],
                priority=f["priority"],
                rationale=f["rationale"],
                implementation_spec=f.get("implementation_spec", ""),
                relevant_files=tuple(f.get("relevant_files", ())),
                boldness=f.get("boldness", "balanced"),
            )
            for f in data
        ]
    except (json.JSONDecodeError, KeyError, TypeError):
        return []


def save_findings(repo: Path, findings: list[Finding]) -> None:
    sigil_dir = repo / SIGIL_DIR
    sigil_dir.mkdir(parents=True, exist_ok=True)
    path = sigil_dir / FINDINGS_FILE
    data = [
        {
            "category": f.category,
            "file": f.file,
            "line": f.line,
            "description": f.description,
            "risk": f.risk,
            "suggested_fix": f.suggested_fix,
            "disposition": f.disposition,
            "priority": f.priority,
            "rationale": f.rationale,
            "implementation_spec": f.implementation_spec,
            "relevant_files": list(f.relevant_files),
            "boldness": f.boldness,
        }
        for f in findings
    ]
    path.write_text(json.dumps(data, indent=2))
