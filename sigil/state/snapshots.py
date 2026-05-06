import hashlib
import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

from sigil.core.config import SIGIL_DIR
from sigil.core.utils import arun, now_utc

logger = logging.getLogger(__name__)

SNAPSHOTS_DIR = "snapshots"


def _snapshots_dir(repo: Path) -> Path:
    return repo / SIGIL_DIR / SNAPSHOTS_DIR


def _prompt_hashes(repo: Path) -> dict[str, str]:
    prompts_path = repo / "sigil" / "pipeline" / "prompts.py"
    if not prompts_path.exists():
        return {}
    try:
        content = prompts_path.read_bytes()
        return {"prompts.py": hashlib.sha256(content).hexdigest()}
    except OSError:
        return {}


async def capture_snapshot(repo: Path, config: object, run_id: str) -> Path:
    rc, stdout, _ = await arun(["git", "rev-parse", "HEAD"], cwd=repo, timeout=10)
    commit = stdout.strip() if rc == 0 else "unknown"

    config_dict = asdict(config)
    model = config_dict.get("model", "")
    agents = config_dict.get("agents", {})

    snapshot = {
        "timestamp": now_utc(),
        "run_id": run_id,
        "commit": commit,
        "model": model,
        "agents": agents,
        "config": config_dict,
        "prompt_hashes": _prompt_hashes(repo),
    }

    snapshots_dir = _snapshots_dir(repo)
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    ts = snapshot["timestamp"].replace(":", "-").replace("+", "-")
    filename = f"{ts}.json"
    path = snapshots_dir / filename
    path.write_text(json.dumps(snapshot, indent=2, default=str))
    return path


def load_snapshot(repo: Path, timestamp: str) -> dict | None:
    snapshots_dir = _snapshots_dir(repo)
    if not snapshots_dir.exists():
        return None

    matches = sorted(snapshots_dir.glob(f"{timestamp}*.json"))
    if not matches:
        return None

    path = matches[-1]
    try:
        data = json.loads(path.read_text())
        return data
    except (json.JSONDecodeError, OSError):
        return None


def prune_snapshots(repo: Path, retention_days: int) -> int:
    snapshots_dir = _snapshots_dir(repo)
    if not snapshots_dir.exists():
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    pruned = 0

    for path in sorted(snapshots_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text())
            ts_str = data.get("timestamp", "")
            if not ts_str:
                continue
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if ts < cutoff:
                path.unlink()
                pruned += 1
        except (json.JSONDecodeError, OSError, ValueError):
            continue

    return pruned


def format_snapshot(snapshot: dict) -> str:
    lines = []
    lines.append(f"Timestamp:  {snapshot.get('timestamp', 'unknown')}")
    lines.append(f"Run ID:     {snapshot.get('run_id', 'unknown')}")
    lines.append(f"Commit:     {snapshot.get('commit', 'unknown')}")
    lines.append(f"Model:      {snapshot.get('model', 'unknown')}")

    agents = snapshot.get("agents", {})
    if agents:
        lines.append("Agent Overrides:")
        for name, cfg in sorted(agents.items()):
            model = cfg.get("model", "(default)")
            lines.append(f"  {name}: {model}")

    prompt_hashes = snapshot.get("prompt_hashes", {})
    if prompt_hashes:
        lines.append("Prompt Hashes:")
        for fname, h in sorted(prompt_hashes.items()):
            lines.append(f"  {fname}: {h[:16]}...")

    config = snapshot.get("config", {})
    if config:
        lines.append("Config:")
        skip = {"agents", "model", "prompt_hashes"}
        for key in sorted(config):
            if key in skip:
                continue
            val = config[key]
            if isinstance(val, (list, tuple)):
                if val:
                    lines.append(f"  {key}:")
                    for item in val:
                        lines.append(f"    - {item}")
                else:
                    lines.append(f"  {key}: []")
            else:
                lines.append(f"  {key}: {val}")

    return "\n".join(lines)
