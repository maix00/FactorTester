from __future__ import annotations

import sqlite3

import orjson
import pytest

import settings as Settings
from server.services import research_graphs
from server.services.maintenance_cases.schema import create_schema
from server.services.research_graph.activation_migration import (
    migrate_graph_activation_pointer,
)
from tools.data.sqlite.db import connect_sqlite


def _create_legacy_fixture(path) -> None:
    with connect_sqlite(path) as conn:
        conn.executescript(
            """
            CREATE TABLE research_graph_versions (
                graph_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                lifecycle TEXT NOT NULL,
                parent_version INTEGER NOT NULL,
                content_hash TEXT NOT NULL,
                graph_json TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY (graph_id, version),
                UNIQUE (graph_id, content_hash)
            );
            CREATE TABLE active_research_graphs (
                graph_id TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                activated_by TEXT NOT NULL,
                activated_at REAL NOT NULL
            );
            CREATE TABLE research_graph_rollbacks (
                rollback_id TEXT PRIMARY KEY,
                graph_id TEXT NOT NULL,
                from_version INTEGER NOT NULL,
                to_version INTEGER NOT NULL,
                actor TEXT NOT NULL,
                reason TEXT NOT NULL,
                grill_evidence_json TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            """
        )
        create_schema(conn)
        conn.executemany(
            """
            INSERT INTO research_graph_versions (
                graph_id, version, lifecycle, parent_version, content_hash,
                graph_json, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "factor-research",
                    2,
                    "draft",
                    1,
                    "a" * 64,
                    '{"graph_id":"factor-research","version":2}',
                    "curator",
                    1.0,
                ),
                (
                    "factor-research",
                    3,
                    "active",
                    2,
                    "b" * 64,
                    '{"graph_id":"factor-research","version":3}',
                    "alice",
                    2.0,
                ),
            ],
        )
        conn.execute(
            """
            INSERT INTO active_research_graphs
            VALUES ('factor-research', 3, 'alice', 2.0)
            """
        )
        conn.execute(
            """
            INSERT INTO research_graph_rollbacks
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "rollback-1",
                "factor-research",
                5,
                3,
                "alice",
                "shadow regression",
                orjson.dumps([{
                    "question": "pointer only?",
                    "answer": "yes",
                }]).decode(),
                3.0,
            ),
        )


def _tables(path) -> set[str]:
    with connect_sqlite(path) as conn:
        return {
            str(row["name"])
            for row in conn.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
                """
            ).fetchall()
        }


def test_activation_pointer_migration_is_explicit_atomic_and_idempotent(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "legacy-pointer.sqlite"
    _create_legacy_fixture(path)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    with pytest.raises(
        RuntimeError,
        match="migrate_graph_activation_pointer",
    ):
        research_graphs.ensure_schema()

    statements: list[str] = []
    original_connect = connect_sqlite

    def traced_connect(*args, **kwargs):
        conn = original_connect(*args, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(
        "server.services.research_graph.activation_migration.connect_sqlite",
        traced_connect,
    )
    report = migrate_graph_activation_pointer(
        db_path=path,
        actor_owner_mapping={"alice": "alice"},
    )
    first_statements = list(statements)
    statements.clear()
    repeated = migrate_graph_activation_pointer(
        db_path=path,
        actor_owner_mapping={"alice": "alice"},
    )

    assert report["active_pointers_validated"] == 1
    assert report["legacy_rollback_rows_projected"] == 1
    assert report["historical_cases_inserted"] == 1
    assert report["schema_tables_removed"] == 1
    assert report["transactions"] == 1
    assert "2f793cc2" in report["rollback_target"]
    assert repeated["transactions"] == 0
    assert "research_graph_rollbacks" not in _tables(path)
    assert sum(
        statement.lstrip().upper().startswith("BEGIN IMMEDIATE")
        for statement in first_statements
    ) == 1
    assert sum(
        statement.lstrip().upper().startswith("COMMIT")
        for statement in first_statements
    ) == 1

    with original_connect(path) as conn:
        pointer = conn.execute(
            "SELECT * FROM active_research_graphs"
        ).fetchone()
        versions = conn.execute(
            "SELECT version, lifecycle FROM research_graph_versions "
            "ORDER BY version"
        ).fetchall()
        history = conn.execute(
            """
            SELECT * FROM research_maintenance_cases
            WHERE kind='pointer_history'
            """
        ).fetchone()
    assert int(pointer["version"]) == 3
    assert [
        (int(row["version"]), str(row["lifecycle"]))
        for row in versions
    ] == [(2, "draft"), (3, "active")]
    assert history["owner_user_id"] == "alice"
    assert history["status"] == "resolved"
    assert "not-an-authorization" in history["change_refs_json"]
    assert "gate-approval:" not in history["change_refs_json"]

    research_graphs.ensure_schema()


def test_activation_pointer_migration_requires_explicit_owner_mapping(
    tmp_path,
) -> None:
    path = tmp_path / "missing-owner.sqlite"
    _create_legacy_fixture(path)

    with pytest.raises(ValueError, match="explicit owner mapping"):
        migrate_graph_activation_pointer(db_path=path)

    assert "research_graph_rollbacks" in _tables(path)
    with connect_sqlite(path) as conn:
        assert conn.execute(
            """
            SELECT COUNT(*) FROM research_maintenance_cases
            WHERE kind='pointer_history'
            """
        ).fetchone()[0] == 0


def test_activation_pointer_migration_rolls_back_failure(
    tmp_path,
) -> None:
    path = tmp_path / "failed-pointer.sqlite"
    _create_legacy_fixture(path)

    def fail(stage: str) -> None:
        if stage == "after_legacy_drop":
            raise RuntimeError("injected failure")

    with pytest.raises(RuntimeError, match="injected failure"):
        migrate_graph_activation_pointer(
            db_path=path,
            actor_owner_mapping={"alice": "alice"},
            failure_injector=fail,
        )

    assert "research_graph_rollbacks" in _tables(path)
    with connect_sqlite(path) as conn:
        assert conn.execute(
            """
            SELECT COUNT(*) FROM research_maintenance_cases
            WHERE kind='pointer_history'
            """
        ).fetchone()[0] == 0


def test_activation_pointer_migration_rejects_dangling_pointer(
    tmp_path,
) -> None:
    path = tmp_path / "dangling-pointer.sqlite"
    _create_legacy_fixture(path)
    with connect_sqlite(path) as conn:
        conn.execute(
            """
            UPDATE active_research_graphs
            SET version=999 WHERE graph_id='factor-research'
            """
        )

    with pytest.raises(ValueError, match="missing Graph version"):
        migrate_graph_activation_pointer(
            db_path=path,
            actor_owner_mapping={"alice": "alice"},
        )
    assert "research_graph_rollbacks" in _tables(path)
