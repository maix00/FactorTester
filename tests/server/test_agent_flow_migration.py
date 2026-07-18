from __future__ import annotations

import hashlib

import pytest

from server.services.agent_flow import (
    AgentFlowStore,
    migrate_legacy_graph_accounting,
)
from tools.data.sqlite.db import connect_sqlite


_LEGACY_TABLES = {
    "research_agent_executions",
    "research_token_budgets",
    "research_token_reservations",
    "research_provider_usage_receipts",
}


def _create_legacy_schema(graph_db) -> None:
    with connect_sqlite(graph_db) as conn:
        conn.executescript(
            """
            CREATE TABLE research_token_budgets (
                scope_id TEXT PRIMARY KEY,
                owner_user_id TEXT NOT NULL,
                token_limit INTEGER NOT NULL,
                used_tokens INTEGER NOT NULL,
                reserved_tokens INTEGER NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE research_token_reservations (
                reservation_id TEXT PRIMARY KEY,
                scope_id TEXT NOT NULL,
                owner_user_id TEXT NOT NULL,
                work_kind TEXT NOT NULL,
                max_input_tokens INTEGER NOT NULL,
                max_output_tokens INTEGER NOT NULL,
                max_total_tokens INTEGER NOT NULL,
                status TEXT NOT NULL,
                expires_at REAL NOT NULL,
                provider_receipt_id TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE research_provider_usage_receipts (
                provider_receipt_id TEXT PRIMARY KEY,
                reservation_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                provider_request_id TEXT NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                usage_attestation TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE research_agent_executions (
                execution_id TEXT PRIMARY KEY,
                owner_user_id TEXT NOT NULL,
                actor_role TEXT NOT NULL,
                model_id TEXT NOT NULL,
                codex_version TEXT NOT NULL,
                reservation_id TEXT NOT NULL,
                authority_scope TEXT NOT NULL,
                agent_principal_hash TEXT NOT NULL,
                lineage_hash TEXT NOT NULL,
                launcher_attestation TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            """
        )


def _legacy_tables(graph_db) -> set[str]:
    with connect_sqlite(graph_db) as conn:
        return {
            str(row["name"])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }.intersection(_LEGACY_TABLES)


def test_migration_atomically_preserves_accounting_and_provenance(
    tmp_path,
) -> None:
    graph_db = tmp_path / "graphs.sqlite"
    _create_legacy_schema(graph_db)
    with connect_sqlite(graph_db) as conn:
        conn.execute(
            "INSERT INTO research_token_budgets VALUES (?, ?, ?, ?, ?, ?)",
            ("scope-1", "alice", 500, 32, 70, 1.0),
        )
        conn.executemany(
            "INSERT INTO research_token_reservations VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "reservation-settled", "scope-1", "alice", "reviewer",
                    100, 40, 140, "committed", 900.0, "receipt-1", 2.0,
                ),
                (
                    "reservation-open", "scope-1", "alice", "researcher",
                    50, 20, 70, "granted", 1200.0, "", 4.0,
                ),
            ],
        )
        conn.execute(
            "INSERT INTO research_provider_usage_receipts VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "receipt-1", "reservation-settled", "provider-a", "request-1",
                24, 8, "provider-attestation", 3.0,
            ),
        )
        conn.execute(
            "INSERT INTO research_agent_executions VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "execution-1", "alice", "reviewer", "model-a", "runtime-a",
                "reservation-settled", "local_research",
                "a" * 64, "b" * 64, "launcher-attestation", 2.5,
            ),
        )

    store = AgentFlowStore(tmp_path / "agent-flow.sqlite")
    report = migrate_legacy_graph_accounting(
        graph_db_path=graph_db,
        store=store,
        agent_id_by_scope={("alice", "scope-1"): "research-agent-1"},
    )

    assert report["budget_periods_migrated"] == 1
    assert report["invocations_migrated"] == 2
    assert report["legacy_tables_dropped"] == 4
    assert report["graph_schema_tables_before"] == 4
    assert report["graph_schema_tables_after"] == 0
    assert report["agent_flow_schema_tables_before"] == 2
    assert report["agent_flow_schema_tables_after"] == 2
    assert report["sql_reads"] > 0
    assert report["sql_writes"] > 0
    assert report["sql_transactions"] == 1
    assert report["latency_ms"] >= 0
    assert "8a42b1ea" in report["rollback_target"]
    assert _legacy_tables(graph_db) == set()
    period = store.load_current_budget_period(
        owner_user_id="alice",
        agent_id="research-agent-1",
    )
    assert period is not None
    assert period["used_tokens"] == 32
    assert period["reserved_tokens"] == 70

    settled = store.load_invocation(
        owner_user_id="alice",
        invocation_id="execution-1",
    )
    assert "legacy_reservation_id" not in settled
    assert "legacy_provider_receipt_id" not in settled
    assert settled["provider_id"] == "provider-a"
    assert settled["reservation_expires_at"] == 900.0
    assert settled["provider_request_hash"] == hashlib.sha256(
        b"request-1"
    ).hexdigest()
    assert settled["provider_attestation_hash"] == hashlib.sha256(
        b"provider-attestation"
    ).hexdigest()
    assert settled["launcher_attestation_hash"] == hashlib.sha256(
        b"launcher-attestation"
    ).hexdigest()

    reserved = store.load_invocation(
        owner_user_id="alice",
        invocation_id="reservation-open",
    )
    assert reserved["status"] == "reserved"
    assert reserved["reservation_expires_at"] == 1200.0


def test_receipt_mismatch_rolls_back_target_and_legacy_drop(tmp_path) -> None:
    graph_db = tmp_path / "graphs.sqlite"
    _create_legacy_schema(graph_db)
    with connect_sqlite(graph_db) as conn:
        conn.execute(
            "INSERT INTO research_token_budgets VALUES (?, ?, ?, ?, ?, ?)",
            ("scope-1", "alice", 100, 12, 0, 1.0),
        )
        conn.execute(
            "INSERT INTO research_token_reservations VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "reservation-1", "scope-1", "alice", "reviewer",
                20, 10, 30, "committed", 900.0, "receipt-1", 2.0,
            ),
        )
        conn.execute(
            "INSERT INTO research_provider_usage_receipts VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "receipt-1", "different-reservation", "provider-a",
                "request-1", 8, 4, "attestation", 3.0,
            ),
        )

    store = AgentFlowStore(tmp_path / "agent-flow.sqlite")
    with pytest.raises(
        ValueError,
        match="receipt does not match reservation",
    ):
        migrate_legacy_graph_accounting(
            graph_db_path=graph_db,
            store=store,
            agent_id_by_scope={
                ("alice", "scope-1"): "research-agent-1",
            },
        )

    assert _legacy_tables(graph_db) == _LEGACY_TABLES
    assert store.load_current_budget_period(
        owner_user_id="alice",
        agent_id="research-agent-1",
    ) is None
    assert store.count_invocations(
        owner_user_id="alice",
        agent_id="research-agent-1",
    ) == 0


def test_budget_aggregate_mismatch_rolls_back_cutover(tmp_path) -> None:
    graph_db = tmp_path / "graphs.sqlite"
    _create_legacy_schema(graph_db)
    with connect_sqlite(graph_db) as conn:
        conn.execute(
            "INSERT INTO research_token_budgets VALUES (?, ?, ?, ?, ?, ?)",
            ("scope-1", "alice", 100, 0, 9, 1.0),
        )
        conn.execute(
            "INSERT INTO research_token_reservations VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "reservation-1", "scope-1", "alice", "researcher",
                20, 10, 30, "granted", 900.0, "", 2.0,
            ),
        )

    store = AgentFlowStore(tmp_path / "agent-flow.sqlite")
    with pytest.raises(ValueError, match="budget aggregate mismatch"):
        migrate_legacy_graph_accounting(
            graph_db_path=graph_db,
            store=store,
            agent_id_by_scope={
                ("alice", "scope-1"): "research-agent-1",
            },
        )

    assert _legacy_tables(graph_db) == _LEGACY_TABLES
    assert store.load_current_budget_period(
        owner_user_id="alice",
        agent_id="research-agent-1",
    ) is None


def test_pending_reset_period_collision_preserves_both_databases(
    tmp_path,
) -> None:
    graph_db = tmp_path / "graphs.sqlite"
    _create_legacy_schema(graph_db)
    with connect_sqlite(graph_db) as conn:
        conn.execute(
            "INSERT INTO research_token_budgets VALUES (?, ?, ?, ?, ?, ?)",
            ("scope-1", "alice", 100, 0, 0, 1.0),
        )

    store = AgentFlowStore(tmp_path / "agent-flow.sqlite")
    original = store.configure_token_limit(
        owner_user_id="alice",
        agent_id="research-agent-1",
        token_limit=200,
    )
    active = store.reserve_invocation(
        owner_user_id="alice",
        agent_id="research-agent-1",
        actor_role="researcher",
        authority_scope="local_research",
        purpose="existing work",
        runtime_id="runtime-a",
        model_id="model-a",
        max_input_tokens=20,
        max_output_tokens=10,
        agent_principal_hash="a" * 64,
        lineage_hash="b" * 64,
    )
    pending = store.reset_budget_period(
        owner_user_id="alice",
        agent_id="research-agent-1",
        token_limit=150,
    )
    assert pending["reset_pending"] is True

    with pytest.raises(ValueError, match="collision with pending reset"):
        migrate_legacy_graph_accounting(
            graph_db_path=graph_db,
            store=store,
            agent_id_by_scope={
                ("alice", "scope-1"): "research-agent-1",
            },
        )

    assert _legacy_tables(graph_db) == _LEGACY_TABLES
    after = store.load_current_budget_period(
        owner_user_id="alice",
        agent_id="research-agent-1",
    )
    assert after is not None
    assert after["period_id"] == original["period_id"]
    assert after["reset_pending"] is True
    assert after["next_token_limit"] == 150
    assert store.load_invocation(
        owner_user_id="alice",
        invocation_id=active["invocation_id"],
    )["status"] == "reserved"


def test_target_constraint_failure_rolls_back_insert_and_source_drop(
    tmp_path,
) -> None:
    graph_db = tmp_path / "graphs.sqlite"
    _create_legacy_schema(graph_db)
    with connect_sqlite(graph_db) as conn:
        conn.execute(
            "INSERT INTO research_token_budgets VALUES (?, ?, ?, ?, ?, ?)",
            ("scope-1", "alice", 100, 12, 0, 1.0),
        )
        conn.execute(
            "INSERT INTO research_token_reservations VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy-reservation", "scope-1", "alice", "reviewer",
                20, 10, 30, "committed", 900.0, "legacy-receipt", 2.0,
            ),
        )
        conn.execute(
            "INSERT INTO research_provider_usage_receipts VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy-receipt", "legacy-reservation", "provider-a",
                "duplicate-request", 8, 4, "attestation", 3.0,
            ),
        )

    store = AgentFlowStore(tmp_path / "agent-flow.sqlite")
    existing = store.reserve_invocation(
        owner_user_id="alice",
        agent_id="existing-agent",
        actor_role="researcher",
        authority_scope="local_research",
        purpose="existing invocation",
        runtime_id="runtime-a",
        model_id="model-a",
        max_input_tokens=20,
        max_output_tokens=10,
        agent_principal_hash="a" * 64,
        lineage_hash="b" * 64,
    )
    store.settle_invocation(
        owner_user_id="alice",
        invocation_id=existing["invocation_id"],
        input_tokens=8,
        output_tokens=4,
        provider_request_id="duplicate-request",
    )

    with pytest.raises(ValueError, match="Agent invocation collision"):
        migrate_legacy_graph_accounting(
            graph_db_path=graph_db,
            store=store,
            agent_id_by_scope={
                ("alice", "scope-1"): "research-agent-1",
            },
        )

    assert _legacy_tables(graph_db) == _LEGACY_TABLES
    assert store.load_current_budget_period(
        owner_user_id="alice",
        agent_id="research-agent-1",
    ) is None
    assert store.count_invocations(
        owner_user_id="alice",
        agent_id="existing-agent",
    ) == 1
