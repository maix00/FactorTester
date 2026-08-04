"""Generic SQLite helpers shared by the data mirrors."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd


class _ClosingConnection(sqlite3.Connection):
    """Commit or roll back a context-managed operation, then release its FD."""

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        try:
            return bool(super().__exit__(exc_type, exc_value, traceback))
        finally:
            self.close()


def connect_sqlite(
    db_path: str | Path,
    *,
    foreign_keys: bool = False,
    readonly: bool = False,
    timeout: float = 30.0,
) -> sqlite3.Connection:
    path = Path(db_path)
    if not readonly:
        path.parent.mkdir(parents=True, exist_ok=True)
    target = f"file:{path}?mode=ro" if readonly else str(path)
    conn = sqlite3.connect(
        target,
        timeout=timeout,
        factory=_ClosingConnection,
        uri=readonly,
    )
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {max(0, int(timeout * 1000))}")
    if foreign_keys:
        conn.execute("PRAGMA foreign_keys = ON")
    return conn


def safe_ident(value: str, *, max_length: int = 80) -> str:
    value = re.sub(r"[^0-9A-Za-z_]+", "_", value.strip())
    value = re.sub(r"_+", "_", value).strip("_")
    if not value:
        value = "x"
    return value[:max_length]


def replace_dataframe(conn: sqlite3.Connection, table_name: str, df: pd.DataFrame) -> None:
    df.to_sql(table_name, conn, if_exists="replace", index=False)


def replace_rows(conn: sqlite3.Connection, table: str, columns: list[str], rows: list[tuple[Any, ...]]) -> None:
    conn.execute(f"DELETE FROM {table}")
    if not rows:
        return
    placeholders = ", ".join("?" for _ in columns)
    conn.executemany(
        f'INSERT OR REPLACE INTO {table} ({", ".join(columns)}) VALUES ({placeholders})',
        rows,
    )
