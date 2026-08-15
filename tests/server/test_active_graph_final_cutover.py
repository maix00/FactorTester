"""Offline final-cutover coordinator acceptance tests."""

from __future__ import annotations

import json

from server.services.research_graph.schema import create_schema
from tools.data.sqlite.db import connect_sqlite
from tools.migrations.finalize_active_graph_cutover import (
    finalize_cutover,
    inspect_cutover,
    main,
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


def _graph_database(tmp_path):
    graph_path = tmp_path / "graph.sqlite"
    with connect_sqlite(graph_path) as conn:
        create_schema(conn)
    return graph_path


def test_final_cutover_is_idempotent_and_has_no_agent_quota_database(
    tmp_path,
) -> None:
    graph_path = _graph_database(tmp_path)

    report = finalize_cutover(
        graph_db_path=graph_path,
        backup_dir=tmp_path / "backups",
    )

    assert report["success"] is True
    assert report["batch_reports"] == {}
    assert report["graph_schema"]["is_final"] is True
    assert (tmp_path / "backups").is_dir()


def test_final_cutover_removes_legacy_graph_control_tables(tmp_path) -> None:
    graph_path = _graph_database(tmp_path)
    with connect_sqlite(graph_path) as conn:
        conn.executescript(
            """
            CREATE TABLE research_token_budgets (
                scope_id TEXT PRIMARY KEY,
                owner_user_id TEXT NOT NULL
            );
            CREATE TABLE research_token_reservations (
                reservation_id TEXT PRIMARY KEY
            );
            CREATE TABLE research_provider_usage_receipts (
                receipt_id TEXT PRIMARY KEY
            );
            CREATE TABLE agent_identity_marker (
                execution_id TEXT PRIMARY KEY
            );
            """
        )

    report = finalize_cutover(
        graph_db_path=graph_path,
        backup_dir=tmp_path / "backups",
    )

    assert report["batch_reports"]["remove_legacy_graph_control"] == {
        "tables_removed": [
            "research_provider_usage_receipts",
            "research_token_budgets",
            "research_token_reservations",
        ],
    }
    assert not _tables(graph_path) & {
        "research_token_budgets",
        "research_token_reservations",
        "research_provider_usage_receipts",
    }
    assert "agent_identity_marker" in _tables(graph_path)


def test_dry_run_reports_legacy_token_tables_without_writing(tmp_path) -> None:
    graph_path = tmp_path / "legacy.sqlite"
    with connect_sqlite(graph_path) as conn:
        conn.execute(
            "CREATE TABLE research_token_budgets "
            "(scope_id TEXT PRIMARY KEY, owner_user_id TEXT NOT NULL)"
        )
    before = graph_path.read_bytes()

    report = inspect_cutover(graph_db_path=graph_path)

    assert report["legacy_token_tables"] == ["research_token_budgets"]
    assert report["planned_batches"] == ["remove_legacy_graph_control"]
    assert graph_path.read_bytes() == before


def test_dry_run_reports_unassured_terminal_jobs_without_legacy_receipts(
    tmp_path,
) -> None:
    graph_path = tmp_path / "unassured.sqlite"
    with connect_sqlite(graph_path) as conn:
        conn.executescript(
            """
            CREATE TABLE research_jobs (
                job_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                terminal_assurance_json TEXT
            );
            INSERT INTO research_jobs VALUES (
                'historical-success',
                'succeeded',
                NULL
            );
            """
        )
    before = graph_path.read_bytes()

    report = inspect_cutover(graph_db_path=graph_path)

    assert report["planned_batches"] == ["backend_assurance"]
    assert graph_path.read_bytes() == before


def test_cli_defaults_to_machine_readable_dry_run(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    graph_path = _graph_database(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "finalize_active_graph_cutover",
            "--graph-db",
            str(graph_path),
        ],
    )

    assert main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["success"] is True
    assert report["mode"] == "dry_run"
