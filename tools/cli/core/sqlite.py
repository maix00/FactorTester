"""Small SQLite connection helper safe for the packaged client."""

from __future__ import annotations

import sqlite3
from pathlib import Path


class _ClosingConnection(sqlite3.Connection):
    """Close the file descriptor after a context-managed transaction."""

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        try:
            return bool(super().__exit__(exc_type, exc_value, traceback))
        finally:
            self.close()


def connect_sqlite(
    path: str | Path,
    *,
    foreign_keys: bool = False,
    readonly: bool = False,
    timeout: float = 30.0,
) -> sqlite3.Connection:
    """Open SQLite without importing the server-side data package."""
    database = Path(path).expanduser().resolve()
    if not readonly:
        database.parent.mkdir(parents=True, exist_ok=True)
    target = f"file:{database}?mode=ro" if readonly else str(database)
    connection = sqlite3.connect(
        target,
        timeout=timeout,
        factory=_ClosingConnection,
        uri=readonly,
    )
    connection.row_factory = sqlite3.Row
    connection.execute(f"PRAGMA busy_timeout = {max(0, int(timeout * 1000))}")
    if foreign_keys:
        connection.execute("PRAGMA foreign_keys = ON")
    return connection


def connect_client_sqlite(path: str | Path) -> sqlite3.Connection:
    """Compatibility name for client-owned writable SQLite stores."""
    return connect_sqlite(path)
