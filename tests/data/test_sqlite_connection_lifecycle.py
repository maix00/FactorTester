"""Lifecycle contract for the shared SQLite connection helper."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tools.data.hub import DataHub, SQLiteStore
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


def test_connect_sqlite_readonly_requires_existing_database_and_closes(tmp_path) -> None:
    path = tmp_path / "readonly.sqlite"
    with connect_sqlite(path) as writer:
        writer.execute("CREATE TABLE values_table (value INTEGER)")
        writer.execute("INSERT INTO values_table VALUES (7)")

    with connect_sqlite(path, readonly=True, timeout=5.0) as reader:
        assert reader.execute(
            "SELECT value FROM values_table"
        ).fetchone()["value"] == 7

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        reader.execute("SELECT 1")

    missing = tmp_path / "missing" / "readonly.sqlite"
    with pytest.raises(sqlite3.OperationalError):
        connect_sqlite(missing, readonly=True)
    assert not missing.exists()


def test_data_hub_context_closes_store_connection(tmp_path) -> None:
    hub = object.__new__(DataHub)
    hub._sqlite_stores = {}
    path = tmp_path / "hub.sqlite"
    hub.register_sqlite_store(
        SQLiteStore(key="test", label="Test", path_getter=lambda: str(path))
    )

    with hub.connect_store("test") as connection:
        connection.execute("CREATE TABLE values_table (value INTEGER)")

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")


def test_production_code_uses_shared_sqlite_connection_factory() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    violations = []
    for root_name in ("server", "sources", "tools"):
        for path in (repo_root / root_name).rglob("*.py"):
            if path in {
                repo_root / "tools/data/sqlite/db.py",
                repo_root / "tools/cli/core/sqlite.py",
            }:
                continue
            # Release/build output is an ignored copy of source files, not
            # production code.  Do not report the same source violation twice
            # merely because a local packaging run left its staging tree.
            if "build" in path.relative_to(repo_root).parts:
                continue
            if "migrations" in path.relative_to(repo_root).parts:
                continue
            if "sqlite3.connect(" in path.read_text(encoding="utf-8"):
                violations.append(str(path.relative_to(repo_root)))

    assert violations == []
