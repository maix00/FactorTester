"""Offline final-cutover coordinator acceptance tests."""

from __future__ import annotations

import json

from server.services.agent_flow import AgentFlowStore
from server.services.agent_flow.schema import (
    AGENT_INVOCATION_COLUMNS,
    LEGACY_INVOCATION_COLUMNS,
    table_columns,
)
from server.services.research_graph.schema import (
    GRAPH_OWNER_TABLES,
    create_schema,
)
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


def _final_databases(tmp_path):
    graph_path = tmp_path / "graph.sqlite"
    flow_path = tmp_path / "flow.sqlite"
    with connect_sqlite(graph_path) as conn:
        create_schema(conn)
    AgentFlowStore(flow_path)
    return graph_path, flow_path


def test_final_cutover_is_idempotent_and_preserves_exact_owner_schemas(
    tmp_path,
) -> None:
    graph_path, flow_path = _final_databases(tmp_path)

    report = finalize_cutover(
        graph_db_path=graph_path,
        agent_flow_db_path=flow_path,
        backup_dir=tmp_path / "backups",
        agent_id_by_scope={},
        rollback_owner_by_actor={},
    )

    assert report["success"] is True
    assert report["batch_reports"] == {}
    assert report["graph_schema"]["is_final"] is True
    assert _tables(graph_path) == set(GRAPH_OWNER_TABLES)
    assert _tables(flow_path) == {
        "agent_budget_periods",
        "agent_invocations",
    }
    assert (tmp_path / "backups").is_dir()


def test_final_cutover_creates_missing_agent_flow_store(
    tmp_path,
) -> None:
    graph_path = tmp_path / "graph.sqlite"
    flow_path = tmp_path / "missing-flow.sqlite"
    with connect_sqlite(graph_path) as conn:
        create_schema(conn)

    report = finalize_cutover(
        graph_db_path=graph_path,
        agent_flow_db_path=flow_path,
        backup_dir=tmp_path / "backups",
        agent_id_by_scope={},
        rollback_owner_by_actor={},
    )

    assert report["batch_reports"]["agent_flow_schema"][
        "schema_created"
    ] is True
    assert _tables(flow_path) == {
        "agent_budget_periods",
        "agent_invocations",
    }


def test_failed_final_verification_restores_both_database_backups(
    tmp_path,
) -> None:
    graph_path, flow_path = _final_databases(tmp_path)
    with connect_sqlite(graph_path) as conn:
        conn.execute("CREATE TABLE local_marker (value TEXT)")
        conn.execute("INSERT INTO local_marker VALUES ('graph-before')")
    with connect_sqlite(flow_path) as conn:
        conn.execute(
            "ALTER TABLE agent_invocations "
            "ADD COLUMN legacy_reservation_id TEXT NOT NULL DEFAULT ''"
        )
        conn.execute(
            "ALTER TABLE agent_invocations "
            "ADD COLUMN legacy_provider_receipt_id TEXT NOT NULL DEFAULT ''"
        )
        conn.execute("CREATE TABLE unexpected_owner (value TEXT)")
        conn.execute("INSERT INTO unexpected_owner VALUES ('flow-before')")
    try:
        finalize_cutover(
            graph_db_path=graph_path,
            agent_flow_db_path=flow_path,
            backup_dir=tmp_path / "backups",
            agent_id_by_scope={},
            rollback_owner_by_actor={},
        )
    except RuntimeError as exc:
        assert "unexpected owners" in str(exc)
    else:
        raise AssertionError("unexpected Agent Flow owner must fail cutover")

    with connect_sqlite(graph_path) as conn:
        assert conn.execute(
            "SELECT value FROM local_marker"
        ).fetchone()["value"] == "graph-before"
    with connect_sqlite(flow_path) as conn:
        assert conn.execute(
            "SELECT value FROM unexpected_owner"
        ).fetchone()["value"] == "flow-before"
        assert LEGACY_INVOCATION_COLUMNS.issubset(
            table_columns(conn, "agent_invocations")
        )


def test_final_cutover_rebuilds_legacy_agent_flow_columns(
    tmp_path,
) -> None:
    graph_path, flow_path = _final_databases(tmp_path)
    store = AgentFlowStore(flow_path)
    invocation = store.reserve_invocation(
        owner_user_id="alice",
        agent_id="research-agent-1",
        actor_role="research",
        authority_scope="local_research",
        purpose="cutover integration",
        runtime_id="runtime-a",
        model_id="model-a",
        max_input_tokens=10,
        max_output_tokens=5,
        agent_principal_hash="a" * 64,
        lineage_hash="b" * 64,
    )
    with connect_sqlite(flow_path) as conn:
        conn.execute(
            "ALTER TABLE agent_invocations "
            "ADD COLUMN legacy_reservation_id TEXT NOT NULL DEFAULT ''"
        )
        conn.execute(
            "ALTER TABLE agent_invocations "
            "ADD COLUMN legacy_provider_receipt_id TEXT NOT NULL DEFAULT ''"
        )
        conn.execute(
            """
            UPDATE agent_invocations
            SET legacy_reservation_id='legacy-reservation',
                legacy_provider_receipt_id='legacy-receipt'
            WHERE invocation_id=?
            """,
            (invocation["invocation_id"],),
        )

    report = finalize_cutover(
        graph_db_path=graph_path,
        agent_flow_db_path=flow_path,
        backup_dir=tmp_path / "backups",
        agent_id_by_scope={},
        rollback_owner_by_actor={},
    )

    assert report["batch_reports"]["agent_flow_schema"][
        "schema_rebuilt"
    ] is True
    with connect_sqlite(flow_path) as conn:
        assert table_columns(
            conn,
            "agent_invocations",
        ) == AGENT_INVOCATION_COLUMNS
        row = conn.execute(
            """
            SELECT provider_id, status FROM agent_invocations
            WHERE invocation_id=?
            """,
            (invocation["invocation_id"],),
        ).fetchone()
    assert row["status"] == "reserved"


def test_dry_run_reports_required_mappings_without_writing(
    tmp_path,
) -> None:
    graph_path = tmp_path / "legacy.sqlite"
    flow_path = tmp_path / "flow.sqlite"
    with connect_sqlite(graph_path) as conn:
        conn.executescript(
            """
            CREATE TABLE research_token_budgets (
                scope_id TEXT PRIMARY KEY,
                owner_user_id TEXT NOT NULL
            );
            CREATE TABLE research_graph_rollbacks (
                rollback_id TEXT PRIMARY KEY,
                actor TEXT NOT NULL
            );
            """
        )
        conn.execute(
            "INSERT INTO research_token_budgets VALUES ('scope-1', 'alice')"
        )
        conn.execute(
            "INSERT INTO research_graph_rollbacks VALUES ('rollback-1', 'bot')"
        )
    before = graph_path.read_bytes()

    report = inspect_cutover(
        graph_db_path=graph_path,
        agent_flow_db_path=flow_path,
    )

    assert report["required_agent_scope_mappings"] == [{
        "owner_user_id": "alice",
        "scope_id": "scope-1",
    }]
    assert report["required_rollback_owner_mappings"] == ["bot"]
    assert report["planned_batches"] == ["agent_flow", "activation_pointer"]
    assert graph_path.read_bytes() == before
    assert not flow_path.exists()


def test_dry_run_reports_unassured_terminal_jobs_without_legacy_receipts(
    tmp_path,
) -> None:
    graph_path = tmp_path / "unassured.sqlite"
    flow_path = tmp_path / "flow.sqlite"
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

    report = inspect_cutover(
        graph_db_path=graph_path,
        agent_flow_db_path=flow_path,
    )

    assert report["planned_batches"] == ["backend_assurance"]
    assert graph_path.read_bytes() == before
    assert not flow_path.exists()


def test_cli_defaults_to_machine_readable_dry_run(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    graph_path, flow_path = _final_databases(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "finalize_active_graph_cutover",
            "--graph-db",
            str(graph_path),
            "--agent-flow-db",
            str(flow_path),
        ],
    )

    assert main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["success"] is True
    assert report["mode"] == "dry_run"
