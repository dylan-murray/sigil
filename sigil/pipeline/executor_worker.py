"""Standalone executor worker for sandboxed execution.

This module is the entry point that runs INSIDE a NemoClaw or Docker sandbox.
It reads a serialized work item + config from a JSON file, runs the executor,
and writes the result back as JSON.

Usage:
  python -m sigil.pipeline.executor_worker /path/to/worker_args.json

The JSON file contains:
  {
    "worktree_path": "/path/to/worktree",
    "config": { ... serialized Config ... },
    "item_type": "finding" | "idea",
    "item": { ... serialized Finding or FeatureIdea ... }
  }

The result is written to:
  /path/to/worktree/.sigil/worker_result.json
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from sigil.core.config import Config
from sigil.pipeline.executor import ExecutionResult, execute
from sigil.pipeline.ideation import FeatureIdea
from sigil.pipeline.maintenance import Finding

RESULT_FILENAME = ".sigil/worker_result.json"


def _deserialize_item(item_type: str, item_data: dict) -> Finding | FeatureIdea:
    if item_type == "finding":
        return Finding(**item_data)
    if item_type == "idea":
        return FeatureIdea(**item_data)
    raise ValueError(f"Unknown item type: {item_type}")


def _serialize_result(
    result: ExecutionResult, tracker_modified: list[str], tracker_created: list[str]
) -> dict:
    return {
        "success": result.success,
        "diff": result.diff,
        "hooks_passed": result.hooks_passed,
        "failed_hook": result.failed_hook,
        "retries": result.retries,
        "failure_reason": result.failure_reason,
        "failure_type": result.failure_type.value if result.failure_type else None,
        "doom_loop_detected": result.doom_loop_detected,
        "summary": result.summary,
        "downgraded": result.downgraded,
        "downgrade_context": result.downgrade_context,
        "tracker_modified": tracker_modified,
        "tracker_created": tracker_created,
    }


async def run_worker(args_path: Path) -> int:
    args_data = json.loads(args_path.read_text())

    worktree_path = Path(args_data["worktree_path"])
    config_data = args_data["config"]
    if "sandbox_allowlist" in config_data and isinstance(config_data["sandbox_allowlist"], list):
        config_data["sandbox_allowlist"] = tuple(config_data["sandbox_allowlist"])
    config = Config(**config_data)
    item = _deserialize_item(args_data["item_type"], args_data["item"])

    result, tracker = await execute(worktree_path, config, item)

    result_path = worktree_path / RESULT_FILENAME
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps(
            _serialize_result(
                result,
                sorted(tracker.modified),
                sorted(tracker.created),
            ),
            indent=2,
        )
    )

    return 0 if result.success else 1


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python -m sigil.pipeline.executor_worker <args_path>", file=sys.stderr)
        sys.exit(2)

    args_path = Path(sys.argv[1])
    if not args_path.exists():
        print(f"Args file not found: {args_path}", file=sys.stderr)
        sys.exit(2)

    exit_code = asyncio.run(run_worker(args_path))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
