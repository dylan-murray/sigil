import json
import logging
from dataclasses import dataclass
from pathlib import Path

from sigil.core.config import memory_dir
from sigil.core.llm import acompletion, safe_max_tokens
from sigil.core.utils import arun

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TemporalInvariant:
    commit_hash: str
    invariant: str
    status: str  # "stable" | "violated" | "evolved"
    rationale: str


class TemporalAnalyzer:
    def __init__(self, model: str):
        self.model = model

    async def extract_invariants(self, repo: Path, commit_range: str) -> list[TemporalInvariant]:
        """
        Analyzes diffs and structural maps across a range of commits to identify stable architectural patterns.
        """
        rc, stdout, _ = await arun(["git", "log", "--pretty=format:%H", commit_range], cwd=repo)
        if rc != 0:
            logger.error("Failed to get commit log for range %s: %s", commit_range, stdout)
            return []

        commits = stdout.strip().splitlines()
        if not commits:
            return []

        # To avoid token exhaustion, we analyze the range as a whole and a few key snapshots
        # rather than every single commit.
        diff_rc, diff_text, _ = await arun(
            ["git", "diff", f"{commits[-1]}..{commits[0]}"], cwd=repo
        )
        if diff_rc != 0:
            return []

        prompt = (
            "You are an architectural historian. Analyze the following git diff across a range of commits "
            "to identify 'architectural invariants' — rules that have remained stable over time "
            "(e.g., 'Module A never imports Module B', 'All API handlers use the Response wrapper').\n\n"
            f"Diff:\n{diff_text[:50000]}\n\n"
            "Respond with a JSON list of invariants: "
            ' [{"invariant": "...", "status": "stable", "rationale": "..."}]'
        )

        msgs = [{"role": "user", "content": prompt}]
        response = await acompletion(
            label="temporal:extract",
            model=self.model,
            messages=msgs,
            temperature=0.0,
            max_tokens=safe_max_tokens(self.model, msgs, requested=2048),
        )

        raw = response.choices[0].message.content or "[]"
        try:
            # Simple JSON extraction
            start = raw.find("[")
            end = raw.rfind("]") + 1
            if start == -1 or end == 0:
                return []
            data = json.loads(raw[start:end])
            return [
                TemporalInvariant(
                    commit_hash=commits[0],
                    invariant=item["invariant"],
                    status=item.get("status", "stable"),
                    rationale=item.get("rationale", ""),
                )
                for item in data
            ]
        except (json.JSONDecodeError, KeyError, IndexError):
            logger.warning("Failed to parse temporal invariants from LLM response")
            return []

    async def detect_drift(
        self, current_code: str, historical_invariants: list[TemporalInvariant]
    ) -> list[str]:
        """
        Compares current code structure against the time-series of invariants to find violations.
        """
        if not historical_invariants:
            return []

        invariants_text = "\n".join(
            [f"- {inv.invariant} (Rationale: {inv.rationale})" for inv in historical_invariants]
        )

        prompt = (
            "You are an architectural auditor. Compare the current code against a set of historical invariants.\n\n"
            f"Historical Invariants:\n{invariants_text}\n\n"
            f"Current Code:\n{current_code[:50000]}\n\n"
            "Identify any violations where the current code drifts from these established patterns. "
            'Respond with a JSON list of violations: ["Violation 1...", "Violation 2..."]'
        )

        msgs = [{"role": "user", "content": prompt}]
        response = await acompletion(
            label="temporal:drift",
            model=self.model,
            messages=msgs,
            temperature=0.0,
            max_tokens=safe_max_tokens(self.model, msgs, requested=2048),
        )

        raw = response.choices[0].message.content or "[]"
        try:
            start = raw.find("[")
            end = raw.rfind("]") + 1
            if start == -1 or end == 0:
                return []
            return json.loads(raw[start:end])
        except (json.JSONDecodeError, TypeError):
            return []

    async def update_temporal_map(self, repo: Path, invariants: list[TemporalInvariant]) -> str:
        """
        Formats and writes the temporal map to the knowledge base.
        """
        mdir = memory_dir(repo)
        mdir.mkdir(parents=True, exist_ok=True)

        content = "# Temporal Architectural Invariants\n\n"
        content += "This file tracks architectural contracts and their evolution over time.\n\n"

        if not invariants:
            content += "No stable invariants identified yet."
        else:
            content += "| Commit | Invariant | Status | Rationale |\n"
            content += "|---|---|---|---|\n"
            for inv in invariants:
                content += f"| {inv.commit_hash[:7]} | {inv.invariant} | {inv.status} | {inv.rationale} |\n"

        target = mdir / "temporal-invariants.md"
        target.write_text(content + "\n")
        return str(target)
