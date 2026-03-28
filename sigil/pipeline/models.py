from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum


class FailureType(str, Enum):
    PRE_HOOK = "pre_hook"
    POST_HOOK = "post_hook"
    NO_CHANGES = "no_changes"
    DOOM_LOOP = "doom_loop"
    WORKTREE = "worktree"
    COMMIT = "commit"
    REBASE = "rebase"


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


ItemStatusCallback = Callable[[str, str], None]
ItemDoneCallback = Callable[[str, bool], None]
