import json
import sys
import time
from typing import TextIO

from sigil.core.llm import get_usage, get_usage_snapshot


class StructuredEmitter:
    def __init__(self, output: TextIO | None = None) -> None:
        self._output = output or sys.stderr
        self._stage_starts: dict[str, float] = {}
        self._run_start: float = time.monotonic()

    def _emit(self, event: dict) -> None:
        self._output.write(json.dumps(event, default=str) + "\n")
        self._output.flush()

    def stage_start(self, stage: str, agent: str | None = None) -> None:
        self._stage_starts[stage] = time.monotonic()
        event: dict = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "level": "info",
            "stage": stage,
            "event": "stage_start",
        }
        if agent is not None:
            event["agent"] = agent
        self._emit(event)

    def stage_end(
        self,
        stage: str,
        findings: int = 0,
        ideas: int = 0,
        status: str = "ok",
        agent: str | None = None,
    ) -> None:
        start = self._stage_starts.pop(stage, None)
        duration = time.monotonic() - start if start is not None else None
        calls, total_tokens, cost = get_usage_snapshot()
        event: dict = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "level": "info",
            "stage": stage,
            "event": "stage_end",
            "duration_s": round(duration, 3) if duration is not None else None,
            "token_usage": {
                "calls": calls,
                "total_tokens": total_tokens,
                "cost_usd": round(cost, 6),
            },
            "findings_count": findings,
            "ideas_count": ideas,
            "status": status,
        }
        if agent is not None:
            event["agent"] = agent
        self._emit(event)

    def run_complete(
        self,
        findings: int = 0,
        ideas: int = 0,
        prs: int = 0,
        issues: int = 0,
        status: str = "ok",
        duration_s: float | None = None,
    ) -> None:
        total_duration = (
            duration_s if duration_s is not None else time.monotonic() - self._run_start
        )
        usage = get_usage()
        event: dict = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "level": "info",
            "stage": "run",
            "event": "run_complete",
            "duration_s": round(total_duration, 3),
            "token_usage": {
                "calls": usage.calls,
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "cost_usd": round(usage.cost_usd, 6),
            },
            "findings_count": findings,
            "ideas_count": ideas,
            "prs_count": prs,
            "issues_count": issues,
            "status": status,
        }
        self._emit(event)
