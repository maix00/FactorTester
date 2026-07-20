from __future__ import annotations

import pytest

from server.services.agent_flow import (
    AgentFlowStore,
    finalize_agent_flow_schema,
)
from server.services.agent_flow.schema import (
    AGENT_BUDGET_PERIOD_COLUMNS,
    AGENT_FLOW_OWNER_TABLES,
    AGENT_INVOCATION_COLUMNS,
    LEGACY_INVOCATION_COLUMNS,
    ensure_schema,
    table_columns,
)
from tools.data.sqlite.db import connect_sqlite


def _seed_invocation(path) -> dict:
    store = AgentFlowStore(path)
    reserved = store.reserve_invocation(
        owner_user_id="alice",
        agent_id="research-agent-1",
        actor_role="research",
        authority_scope="local_research",
        purpose="test final schema",
        runtime_id="runtime-a",
        model_id="model-a",
        max_input_tokens=20,
        max_output_tokens=10,
        agent_principal_hash="a" * 64,
        lineage_hash="b" * 64,
    )
    store.settle_invocation(
        owner_user_id="alice",
        invocation_id=reserved["invocation_id"],
        input_tokens=8,
        output_tokens=3,
        provider_request_id="provider-request-1",
        provider_attestation="provider-attestation-1",
    )
    return store.load_invocation(
        owner_user_id="alice",
        invocation_id=reserved["invocation_id"],
    )


def _add_legacy_columns(path, invocation_id: str) -> None:
    with connect_sqlite(path) as conn:
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
            (invocation_id,),
        )


def test_fresh_and_loaded_invocations_expose_only_final_columns(
    tmp_path,
) -> None:
    path = tmp_path / "fresh.sqlite"
    invocation = _seed_invocation(path)

    with connect_sqlite(path) as conn:
        assert table_columns(
            conn,
            "agent_budget_periods",
        ) == AGENT_BUDGET_PERIOD_COLUMNS
        assert table_columns(
            conn,
            "agent_invocations",
        ) == AGENT_INVOCATION_COLUMNS
    assert LEGACY_INVOCATION_COLUMNS.isdisjoint(invocation)
    assert invocation["provider_request_hash"]
    assert invocation["provider_attestation_hash"]
    assert invocation["launcher_attestation_hash"] == ""


def test_offline_finalizer_creates_a_missing_agent_flow_database(
    tmp_path,
) -> None:
    path = tmp_path / "missing.sqlite"

    report = finalize_agent_flow_schema(db_path=path)

    with connect_sqlite(path) as conn:
        tables = {
            str(row["name"])
            for row in conn.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
                """
            ).fetchall()
        }
    assert tables == set(AGENT_FLOW_OWNER_TABLES)
    assert report["schema_created"] is True
    assert report["schema_rebuilt"] is False


def test_offline_finalizer_rejects_unexpected_owner_tables(
    tmp_path,
) -> None:
    path = tmp_path / "unexpected.sqlite"
    with connect_sqlite(path) as conn:
        conn.execute("CREATE TABLE unexpected_owner (value TEXT)")

    with pytest.raises(ValueError, match="owner schema"):
        finalize_agent_flow_schema(db_path=path)


def test_runtime_rejects_legacy_columns_without_writing(
    tmp_path,
) -> None:
    path = tmp_path / "legacy-runtime.sqlite"
    invocation = _seed_invocation(path)
    _add_legacy_columns(path, invocation["invocation_id"])
    before = path.read_bytes()

    with pytest.raises(
        RuntimeError,
        match="finalize_active_graph_cutover",
    ):
        ensure_schema(path)

    assert path.read_bytes() == before


def test_offline_finalizer_rebuilds_atomically_and_is_restart_safe(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "legacy-finalize.sqlite"
    invocation = _seed_invocation(path)
    _add_legacy_columns(path, invocation["invocation_id"])
    statements: list[str] = []
    original_connect = connect_sqlite

    def traced_connect(*args, **kwargs):
        conn = original_connect(*args, **kwargs, foreign_keys=True)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(
        "server.services.agent_flow.final_schema.connect_agent_flow",
        traced_connect,
    )
    report = finalize_agent_flow_schema(db_path=path)
    first_statements = list(statements)
    statements.clear()
    repeated = finalize_agent_flow_schema(db_path=path)

    assert report["schema_rebuilt"] is True
    assert report["invocations_preserved"] == 1
    assert set(report["legacy_columns_removed"]) == (
        LEGACY_INVOCATION_COLUMNS
    )
    assert repeated["schema_rebuilt"] is False
    assert sum(
        statement.lstrip().upper().startswith("BEGIN IMMEDIATE")
        for statement in first_statements
    ) == 1
    assert sum(
        statement.lstrip().upper().startswith("COMMIT")
        for statement in first_statements
    ) == 1

    restarted = AgentFlowStore(path)
    loaded = restarted.load_invocation(
        owner_user_id="alice",
        invocation_id=invocation["invocation_id"],
    )
    assert LEGACY_INVOCATION_COLUMNS.isdisjoint(loaded)
    for field in (
        "provider_id",
        "provider_request_hash",
        "provider_attestation_hash",
        "agent_principal_hash",
        "lineage_hash",
    ):
        assert loaded[field] == invocation[field]
    with connect_sqlite(path) as conn:
        assert table_columns(
            conn,
            "agent_invocations",
        ) == AGENT_INVOCATION_COLUMNS


def test_offline_finalizer_failure_restores_original_table(
    tmp_path,
) -> None:
    path = tmp_path / "atomic-rollback.sqlite"
    invocation = _seed_invocation(path)
    _add_legacy_columns(path, invocation["invocation_id"])

    with pytest.raises(RuntimeError, match="injected"):
        finalize_agent_flow_schema(
            db_path=path,
            failure_injector=lambda stage: (
                (_ for _ in ()).throw(RuntimeError("injected"))
                if stage == "after_canonical_copy"
                else None
            ),
        )

    with connect_sqlite(path) as conn:
        assert LEGACY_INVOCATION_COLUMNS.issubset(
            table_columns(conn, "agent_invocations")
        )
        row = conn.execute(
            """
            SELECT legacy_reservation_id, legacy_provider_receipt_id
            FROM agent_invocations WHERE invocation_id=?
            """,
            (invocation["invocation_id"],),
        ).fetchone()
    assert row["legacy_reservation_id"] == "legacy-reservation"
    assert row["legacy_provider_receipt_id"] == "legacy-receipt"


def test_warm_schema_check_is_read_only_and_schema_bounded(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "warm.sqlite"
    AgentFlowStore(path)
    statements: list[str] = []
    original_connect = connect_sqlite

    def traced_connect(*args, **kwargs):
        conn = original_connect(*args, **kwargs, foreign_keys=True)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(
        "server.services.agent_flow.schema.connect_agent_flow",
        traced_connect,
    )
    ensure_schema(path)
    normalized = [" ".join(item.upper().split()) for item in statements]

    assert sum(item.startswith("SELECT ") for item in normalized) == 1
    assert sum(item.startswith("PRAGMA TABLE_INFO") for item in normalized) == 2
    assert not any(
        item.startswith((
            "CREATE ",
            "ALTER ",
            "DROP ",
            "INSERT ",
            "UPDATE ",
            "DELETE ",
        ))
        for item in normalized
    )
