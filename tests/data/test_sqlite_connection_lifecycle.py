"""Lifecycle contract for the shared SQLite connection helper."""

from __future__ import annotations

import sqlite3

import pytest

from tools.data.sqlite.db import connect_sqlite


def test_connect_sqlite_context_commits_then_closes(tmp_path) -> None:
    path = tmp_path / "lifecycle.sqlite"

    with connect_sqlite(path) as connection:
        connection.execute("CREATE TABLE values_table (value INTEGER)")
        connection.execute("INSERT INTO values_table VALUES (1)")

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")

    with connect_sqlite(path) as verifier:
        assert verifier.execute(
            "SELECT value FROM values_table"
        ).fetchone()["value"] == 1


def test_connect_sqlite_context_rolls_back_then_closes(tmp_path) -> None:
    path = tmp_path / "rollback.sqlite"
    connection = connect_sqlite(path)

    with pytest.raises(RuntimeError, match="rollback"):
        with connection:
            connection.execute("CREATE TABLE values_table (value INTEGER)")
            connection.execute("INSERT INTO values_table VALUES (1)")
            raise RuntimeError("rollback")

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")

