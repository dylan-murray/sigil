import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


BOLDNESS_RANK: dict[str, int] = {
    "conservative": 0,
    "balanced": 1,
    "bold": 2,
    "experimental": 3,
}


def boldness_allowed(item_boldness: str, current_boldness: str) -> bool:
    return BOLDNESS_RANK.get(item_boldness, 1) <= BOLDNESS_RANK.get(current_boldness, 1)


@dataclass(frozen=True)
class Finding:
    category: str
    file: str
    line: int | None
    description: str
    risk: str
    suggested_fix: str
    disposition: str
    priority: int
    rationale: str
    implementation_spec: str = ""
    relevant_files: tuple[str, ...] = ()
    boldness: str = "balanced"


@dataclass(frozen=True)
class FeatureIdea:
    title: str
    description: str
    rationale: str
    complexity: str
    disposition: str
    priority: int
    implementation_spec: str = ""
    relevant_files: tuple[str, ...] = ()
    boldness: str = "balanced"


@dataclass(frozen=True)
class ReviewDecision:
    action: str
    new_disposition: str | None
    reason: str
    spec: str = ""
    relevant_files: list[str] | None = None
    priority: int = 99


ReviewDecisions = dict[int, ReviewDecision]


@dataclass(frozen=True)
class ValidationResult:
    findings: list[Finding]
    ideas: list[FeatureIdea]


class FailureType(str, Enum):
    PRE_HOOK = "pre_hook"
    POST_HOOK = "post_hook"
    NO_CHANGES = "no_changes"
    DOOM_LOOP = "doom_loop"
    WORKTREE = "worktree"
    COMMIT = "commit"
    REBASE = "rebase"
    CONTEXTUAL_BLINDNESS = "contextual_blindness"


@dataclass(frozen=True)
class ExecutionResult:
    success: bool
    diff: str
    hooks_passed: bool
    failed_hook: str | None
    retries: int
    failure_reason: str | None
    failure_type: FailureType | None = None
    doom_loop_detected: bool = False
    summary: str = ""
    downgraded: bool = False
    downgrade_context: str = ""


@dataclass
class FileTracker:
    modified: set[str]
    created: set[str]
    last_read: dict[str, float]

    def __init__(self) -> None:
        self.modified = set()
        self.created = set()
        self.last_read = {}
        self.read_keys: dict[str, int] = {}
        self.read_totals: dict[str, int] = {}

    def reset_read_counters(self) -> None:
        self.read_keys.clear()
        self.read_totals.clear()
        self.last_read.clear()

    def record_read(self, repo: Path, file: str) -> None:
        try:
            self.last_read[file] = (repo / file).stat().st_mtime
        except OSError:
            self.last_read[file] = time.time()

    def check_staleness(self, repo: Path, file: str) -> str | None:
        if file not in self.last_read:
            return (
                f"You must read {file} before editing it. Use read_file first, "
                f"then use the EXACT content from that read as your old_content."
            )
        path = repo / file
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return None
        if mtime != self.last_read[file]:
            self.last_read.pop(file, None)
            return (
                f"{file} has been modified since you last read it. "
                f"Re-read the file with read_file before editing."
            )
        return None


ItemStatusCallback = Callable[[str, str], None]
ItemDoneCallback = Callable[[str, bool], None]
