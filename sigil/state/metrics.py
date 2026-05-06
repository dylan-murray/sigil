import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from sigil.core.config import SIGIL_DIR

METRICS_DB = "metrics.db"

_CREATE_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    total_findings INTEGER NOT NULL,
    total_ideas INTEGER NOT NULL,
    findings_by_category TEXT NOT NULL,
    findings_by_risk TEXT NOT NULL,
    execution_success_count INTEGER NOT NULL,
    execution_total_count INTEGER NOT NULL,
    tokens_consumed INTEGER NOT NULL,
    cost_usd REAL NOT NULL,
    wall_clock_seconds REAL NOT NULL
)
"""


@dataclass(frozen=True)
class RunMetrics:
    timestamp: str
    total_findings: int
    total_ideas: int
    findings_by_category: dict[str, int]
    findings_by_risk: dict[str, int]
    execution_success_count: int
    execution_total_count: int
    tokens_consumed: int
    cost_usd: float
    wall_clock_seconds: float


def _db_path(repo: Path) -> Path:
    return repo / SIGIL_DIR / METRICS_DB


def init_db(repo: Path) -> None:
    db_path = _db_path(repo)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(_CREATE_TABLE_SQL)
        conn.commit()


def record_run(repo: Path, metrics: RunMetrics) -> None:
    db_path = _db_path(repo)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """\
            INSERT INTO runs (
                timestamp, total_findings, total_ideas,
                findings_by_category, findings_by_risk,
                execution_success_count, execution_total_count,
                tokens_consumed, cost_usd, wall_clock_seconds
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                metrics.timestamp,
                metrics.total_findings,
                metrics.total_ideas,
                json.dumps(metrics.findings_by_category),
                json.dumps(metrics.findings_by_risk),
                metrics.execution_success_count,
                metrics.execution_total_count,
                metrics.tokens_consumed,
                metrics.cost_usd,
                metrics.wall_clock_seconds,
            ),
        )
        conn.commit()


def query_runs(repo: Path, limit: int = 10, category: str | None = None) -> list[RunMetrics]:
    db_path = _db_path(repo)
    if not db_path.exists():
        return []
    with sqlite3.connect(str(db_path)) as conn:
        if category is not None:
            rows = conn.execute(
                """\
                SELECT timestamp, total_findings, total_ideas,
                       findings_by_category, findings_by_risk,
                       execution_success_count, execution_total_count,
                       tokens_consumed, cost_usd, wall_clock_seconds
                FROM runs
                WHERE findings_by_category LIKE ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (f'%"{category}"%', limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """\
                SELECT timestamp, total_findings, total_ideas,
                       findings_by_category, findings_by_risk,
                       execution_success_count, execution_total_count,
                       tokens_consumed, cost_usd, wall_clock_seconds
                FROM runs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    results: list[RunMetrics] = []
    for row in rows:
        results.append(
            RunMetrics(
                timestamp=row[0],
                total_findings=row[1],
                total_ideas=row[2],
                findings_by_category=json.loads(row[3]),
                findings_by_risk=json.loads(row[4]),
                execution_success_count=row[5],
                execution_total_count=row[6],
                tokens_consumed=row[7],
                cost_usd=row[8],
                wall_clock_seconds=row[9],
            )
        )
    results.reverse()
    return results
