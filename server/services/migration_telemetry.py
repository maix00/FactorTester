"""Small, deterministic release evidence for explicit offline migrations."""

from __future__ import annotations

from dataclasses import dataclass, field
import sqlite3
import time
from typing import Any


@dataclass
class MigrationTelemetry:
    """Collect statement classes and elapsed time without persisting telemetry."""

    started: float = field(default_factory=time.perf_counter)
    statements: list[str] = field(default_factory=list)

    def trace(self, statement: str) -> None:
        self.statements.append(" ".join(statement.upper().split()))

    def report(self) -> dict[str, Any]:
        return {
            "sql_reads": _count_prefixes(self.statements, ("SELECT ",)),
            "sql_writes": _count_prefixes(
                self.statements,
                ("INSERT ", "UPDATE ", "DELETE ", "REPLACE "),
            ),
            "sql_ddl": _count_prefixes(
                self.statements,
                ("CREATE ", "ALTER ", "DROP "),
            ),
            "sql_transactions": _count_prefixes(
                self.statements,
                ("BEGIN ",),
            ),
            "latency_ms": round(
                (time.perf_counter() - self.started) * 1000,
                3,
            ),
        }


def table_count(
    conn: sqlite3.Connection,
    *,
    schema: str = "main",
) -> int:
    if schema not in {"main", "legacy_graph"}:
        raise ValueError(f"unsupported SQLite schema: {schema}")
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS count FROM {schema}.sqlite_master
        WHERE type='table' AND name NOT LIKE 'sqlite_%'
        """
    ).fetchone()
    return int(row["count"] if isinstance(row, sqlite3.Row) else row[0])


def _count_prefixes(
    statements: list[str],
    prefixes: tuple[str, ...],
) -> int:
    return sum(statement.startswith(prefixes) for statement in statements)
