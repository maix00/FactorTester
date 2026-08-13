"""Shared connection lifecycle for focused transfer SQLite adapters."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from tools.data.sqlite.db import connect_sqlite

from server.manager.storage.transfers.records import required
from server.manager.storage.transfers.schema import ensure_transfer_schema


class TransferDatabase:
    def __init__(self, path: str | Path, *, server_id: str) -> None:
        self.path = Path(path).expanduser().resolve()
        self.server_id = required(server_id, field="server_id")
        self._schema_lock = threading.Lock()
        self._schema_ready = False
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = connect_sqlite(self.path, foreign_keys=True)
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            with self._connect() as connection:
                ensure_transfer_schema(connection)
            self._schema_ready = True

