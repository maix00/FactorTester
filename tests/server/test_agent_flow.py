from __future__ import annotations

import pytest
from flask import Flask

import settings as Settings
from server.modules.single_factor_test import sft_bp
from server.services import agent_flow, research_graphs
from server.services.agent_flow import (
    AgentFlowStore,
    migrate_legacy_graph_accounting,
)
from server.services.agent_flow import invocations as invocation_module
from tools.data.sqlite.db import connect_sqlite


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(
        Settings,
        "CACHE_DB_PATH",
        tmp_path / "graphs.sqlite",
    )
    agent_flow.clear_store_cache()
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "alice"
    return client


def test_uncapped_agent_invocation_settles_without_provider_attestation(
    tmp_path,
) -> None:
    store = AgentFlowStore(tmp_path / "agent-flow.sqlite")

    invocation = store.reserve_invocation(
        owner_user_id="alice",
        agent_id="research-agent-1",
        actor_role="research",
        authority_scope="local_research",
        purpose="evaluate current hypothesis branch",
        runtime_id="runtime-from-another-provider",
        model_id="provider-neutral-model",
        max_input_tokens=100,
        max_output_tokens=40,
        agent_principal_hash="a" * 64,
        lineage_hash="b" * 64,
    )

    assert invocation["status"] == "reserved"
    assert invocation["token_limit"] is None
    assert invocation["reserved_tokens"] == 140

    settled = store.settle_invocation(
        owner_user_id="alice",
        invocation_id=invocation["invocation_id"],
        input_tokens=24,
        output_tokens=8,
        cache_read_tokens=5,
        provider_request_id="provider-request-1",
    )

    assert settled["status"] == "settled"
    assert settled["charged_tokens"] == 32
    assert settled["measurement_quality"] == "provider_actual"
    assert settled["released_tokens"] == 108

    period = store.load_current_budget_period(
        owner_user_id="alice",
        agent_id="research-agent-1",
    )
    assert period == {
        "period_id": invocation["period_id"],
        "owner_user_id": "alice",
        "agent_id": "research-agent-1",
        "token_limit": None,
        "used_tokens": 32,
        "reserved_tokens": 0,
        "available_tokens": None,
        "charging_policy_version": "normalized-total@1",
        "revision": 1,
        "status": "open",
    }


def test_routine_reserve_and_settle_keep_the_sql_floor(
    tmp_path,
    monkeypatch,
) -> None:
    store = AgentFlowStore(tmp_path / "agent-flow.sqlite")
    statements: list[str] = []
    connect = invocation_module.connect_agent_flow

    def traced_connect(db_path):
        connection = connect(db_path)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(
        invocation_module,
        "connect_agent_flow",
        traced_connect,
    )
    invocation = store.reserve_invocation(
        owner_user_id="alice",
        agent_id="research-agent-1",
        actor_role="research",
        authority_scope="local_research",
        purpose="measure routine SQL",
        runtime_id="runtime-a",
        model_id="model-a",
        max_input_tokens=100,
        max_output_tokens=40,
        agent_principal_hash="a" * 64,
        lineage_hash="b" * 64,
    )
    reserve_statements = [
        statement.strip().upper() for statement in statements
    ]
    statements.clear()

    store.settle_invocation(
        owner_user_id="alice",
        invocation_id=invocation["invocation_id"],
        input_tokens=24,
        output_tokens=8,
    )
    settle_statements = [
        statement.strip().upper() for statement in statements
    ]

    assert sum(
        statement.startswith("SELECT")
        for statement in reserve_statements
    ) == 1
    assert sum(
        statement.startswith(("INSERT", "UPDATE", "DELETE"))
        for statement in reserve_statements
    ) == 3
    assert sum(
        statement.startswith("SELECT")
        for statement in settle_statements
    ) == 1
    assert "JOIN AGENT_BUDGET_PERIODS" in next(
        statement
        for statement in settle_statements
        if statement.startswith("SELECT")
    )
    assert sum(
        statement.startswith(("INSERT", "UPDATE", "DELETE"))
        for statement in settle_statements
    ) == 2


def test_configured_cap_denies_before_call_and_falls_back_to_reservation(
    tmp_path,
) -> None:
    store = AgentFlowStore(tmp_path / "agent-flow.sqlite")
    period = store.configure_token_limit(
        owner_user_id="alice",
        agent_id="research-agent-1",
        token_limit=100,
    )
    assert period["token_limit"] == 100
    unchanged = store.configure_token_limit(
        owner_user_id="alice",
        agent_id="research-agent-1",
        token_limit=100,
    )
    assert unchanged["revision"] == period["revision"]

    invocation = store.reserve_invocation(
        owner_user_id="alice",
        agent_id="research-agent-1",
        actor_role="research",
        authority_scope="local_research",
        purpose="bounded call",
        runtime_id="runtime-a",
        model_id="model-a",
        max_input_tokens=60,
        max_output_tokens=20,
        agent_principal_hash="a" * 64,
        lineage_hash="b" * 64,
    )
    with pytest.raises(
        ValueError,
        match="token_limit cannot be below used plus reserved tokens",
    ):
        store.configure_token_limit(
            owner_user_id="alice",
            agent_id="research-agent-1",
            token_limit=50,
        )

    with pytest.raises(
        ValueError,
        match=r"agent_budget_exhausted: requested=30, available=20",
    ):
        store.reserve_invocation(
            owner_user_id="alice",
            agent_id="research-agent-1",
            actor_role="reviewer",
            authority_scope="local_research",
            purpose="must not start",
            runtime_id="runtime-b",
            model_id="model-b",
            max_input_tokens=20,
            max_output_tokens=10,
            agent_principal_hash="c" * 64,
            lineage_hash="d" * 64,
        )

    settled = store.settle_invocation(
        owner_user_id="alice",
        invocation_id=invocation["invocation_id"],
    )
    assert settled["charged_tokens"] == 80
    assert settled["measurement_quality"] == "reserved_fallback"
    assert settled["released_tokens"] == 0

    current = store.load_current_budget_period(
        owner_user_id="alice",
        agent_id="research-agent-1",
    )
    assert current is not None
    assert current["used_tokens"] == 80
    assert current["reserved_tokens"] == 0
    assert current["available_tokens"] == 20


def test_manual_reset_opens_new_period_without_erasing_usage(
    tmp_path,
) -> None:
    store = AgentFlowStore(tmp_path / "agent-flow.sqlite")
    old_period = store.configure_token_limit(
        owner_user_id="alice",
        agent_id="research-agent-1",
        token_limit=100,
    )
    invocation = store.reserve_invocation(
        owner_user_id="alice",
        agent_id="research-agent-1",
        actor_role="research",
        authority_scope="local_research",
        purpose="first period work",
        runtime_id="runtime-a",
        model_id="model-a",
        max_input_tokens=20,
        max_output_tokens=10,
        agent_principal_hash="a" * 64,
        lineage_hash="b" * 64,
    )
    store.settle_invocation(
        owner_user_id="alice",
        invocation_id=invocation["invocation_id"],
        input_tokens=12,
        output_tokens=3,
    )

    new_period = store.reset_budget_period(
        owner_user_id="alice",
        agent_id="research-agent-1",
        token_limit=50,
    )

    assert new_period["period_id"] != old_period["period_id"]
    assert new_period["token_limit"] == 50
    assert new_period["used_tokens"] == 0
    history = store.list_budget_periods(
        owner_user_id="alice",
        agent_id="research-agent-1",
    )
    assert [
        (item["period_id"], item["status"], item["used_tokens"])
        for item in history
    ] == [
        (new_period["period_id"], "open", 0),
        (old_period["period_id"], "closed", 15),
    ]


def test_reset_waits_for_active_invocation_then_opens_new_period(
    tmp_path,
) -> None:
    store = AgentFlowStore(tmp_path / "agent-flow.sqlite")
    old_period = store.configure_token_limit(
        owner_user_id="alice",
        agent_id="research-agent-1",
        token_limit=100,
    )
    invocation = store.reserve_invocation(
        owner_user_id="alice",
        agent_id="research-agent-1",
        actor_role="research",
        authority_scope="local_research",
        purpose="active during reset",
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
        token_limit=50,
    )
    assert pending["period_id"] == old_period["period_id"]
    assert pending["reset_pending"] is True
    assert pending["next_token_limit"] == 50
    with pytest.raises(ValueError, match="budget reset is pending"):
        store.reserve_invocation(
            owner_user_id="alice",
            agent_id="research-agent-1",
            actor_role="reviewer",
            authority_scope="local_research",
            purpose="must wait for new period",
            runtime_id="runtime-a",
            model_id="model-a",
            max_input_tokens=5,
            max_output_tokens=5,
            agent_principal_hash="c" * 64,
            lineage_hash="d" * 64,
        )

    store.settle_invocation(
        owner_user_id="alice",
        invocation_id=invocation["invocation_id"],
        input_tokens=10,
        output_tokens=5,
    )
    current = store.load_current_budget_period(
        owner_user_id="alice",
        agent_id="research-agent-1",
    )
    assert current is not None
    assert current["period_id"] != old_period["period_id"]
    assert current["token_limit"] == 50
    assert current["used_tokens"] == 0


def test_pending_reset_waits_for_every_reserved_invocation(
    tmp_path,
) -> None:
    store = AgentFlowStore(tmp_path / "agent-flow.sqlite")
    old_period = store.configure_token_limit(
        owner_user_id="alice",
        agent_id="research-agent-1",
        token_limit=100,
    )
    invocations = [
        store.reserve_invocation(
            owner_user_id="alice",
            agent_id="research-agent-1",
            actor_role="research",
            authority_scope="local_research",
            purpose=f"active call {index}",
            runtime_id="runtime-a",
            model_id="model-a",
            max_input_tokens=20,
            max_output_tokens=10,
            agent_principal_hash=str(index) * 64,
            lineage_hash=str(index + 2) * 64,
        )
        for index in (1, 2)
    ]
    store.reset_budget_period(
        owner_user_id="alice",
        agent_id="research-agent-1",
        token_limit=50,
    )

    store.settle_invocation(
        owner_user_id="alice",
        invocation_id=invocations[0]["invocation_id"],
        input_tokens=10,
        output_tokens=5,
    )
    still_pending = store.load_current_budget_period(
        owner_user_id="alice",
        agent_id="research-agent-1",
    )
    assert still_pending is not None
    assert still_pending["period_id"] == old_period["period_id"]
    assert still_pending["reserved_tokens"] == 30
    assert still_pending["reset_pending"] is True

    store.settle_invocation(
        owner_user_id="alice",
        invocation_id=invocations[1]["invocation_id"],
        input_tokens=10,
        output_tokens=5,
    )
    reset = store.load_current_budget_period(
        owner_user_id="alice",
        agent_id="research-agent-1",
    )
    assert reset is not None
    assert reset["period_id"] != old_period["period_id"]
    assert reset["token_limit"] == 50


def test_legacy_accounting_migrates_once_without_dual_write(
    tmp_path,
) -> None:
    graph_db = tmp_path / "graphs.sqlite"
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
        conn.execute(
            """
            INSERT INTO research_token_budgets
            VALUES ('agent-1', 'alice', 100, 32, 0, 1.0)
            """
        )
        conn.execute(
            """
            INSERT INTO research_token_reservations
            VALUES (
                'reservation-1', 'agent-1', 'alice', 'reviewer',
                100, 40, 140, 'committed', 999.0, 'receipt-1', 2.0
            )
            """
        )
        conn.execute(
            """
            INSERT INTO research_provider_usage_receipts
            VALUES (
                'receipt-1', 'reservation-1', 'provider-a', 'request-1',
                24, 8, 'same-owner-hmac', 3.0
            )
            """
        )
        conn.execute(
            """
            INSERT INTO research_agent_executions
            VALUES (
                'execution-1', 'alice', 'reviewer', 'model-a', 'codex-a',
                'reservation-1', 'local_research', ?, ?, 'launcher-hmac', 2.5
            )
            """,
            ("a" * 64, "b" * 64),
        )

    store = AgentFlowStore(tmp_path / "agent-flow.sqlite")
    report = migrate_legacy_graph_accounting(
        graph_db_path=graph_db,
        store=store,
        agent_id_by_scope={
            ("alice", "agent-1"): "research-agent-1",
        },
    )

    assert report == {
        "budget_periods_migrated": 1,
        "invocations_migrated": 1,
        "legacy_tables_dropped": 4,
    }
    period = store.load_current_budget_period(
        owner_user_id="alice",
        agent_id="research-agent-1",
    )
    assert period is not None
    assert period["used_tokens"] == 32
    invocation = store.load_invocation(
        owner_user_id="alice",
        invocation_id="execution-1",
    )
    assert invocation["legacy_reservation_id"] == "reservation-1"
    assert invocation["runtime_id"] == "codex-a"
    assert invocation["model_id"] == "model-a"
    assert invocation["charged_tokens"] == 32
    assert invocation["measurement_quality"] == "provider_actual"

    with connect_sqlite(graph_db) as conn:
        tables = {
            str(row["name"])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert not tables.intersection(
        {
            "research_agent_executions",
            "research_token_budgets",
            "research_token_reservations",
            "research_provider_usage_receipts",
        }
    )


def test_http_invocation_path_is_provider_neutral(client) -> None:
    reserve_response = client.post(
        "/api/agent-flow/invocations",
        json={
            "agent_id": "research-agent-1",
            "actor_role": "research",
            "authority_scope": "local_research",
            "purpose": "continue current branch",
            "runtime_id": "runtime-a",
            "model_id": "model-a",
            "max_input_tokens": 100,
            "max_output_tokens": 40,
            "agent_principal_hash": "a" * 64,
            "lineage_hash": "b" * 64,
        },
    )
    assert reserve_response.status_code == 201
    invocation = reserve_response.get_json()["invocation"]

    settle_response = client.post(
        f"/api/agent-flow/invocations/{invocation['invocation_id']}/settle",
        json={
            "input_tokens": 24,
            "output_tokens": 8,
            "cache_read_tokens": 5,
            "provider_request_id": "request-1",
        },
    )
    assert settle_response.status_code == 200
    assert settle_response.get_json()["invocation"]["charged_tokens"] == 32


def test_invocation_reserve_and_settle_are_request_idempotent(
    tmp_path,
) -> None:
    store = AgentFlowStore(tmp_path / "agent-flow.sqlite")
    request = {
        "owner_user_id": "alice",
        "agent_id": "research-agent-1",
        "actor_role": "research",
        "authority_scope": "local_research",
        "purpose": "retry-safe call",
        "runtime_id": "runtime-a",
        "model_id": "model-a",
        "max_input_tokens": 100,
        "max_output_tokens": 40,
        "agent_principal_hash": "a" * 64,
        "lineage_hash": "b" * 64,
        "idempotency_key": "caller-request-1",
    }
    first = store.reserve_invocation(**request)
    retry = store.reserve_invocation(**request)
    assert retry["invocation_id"] == first["invocation_id"]
    period = store.load_current_budget_period(
        owner_user_id="alice",
        agent_id="research-agent-1",
    )
    assert period is not None
    assert period["reserved_tokens"] == 140

    settled = store.settle_invocation(
        owner_user_id="alice",
        invocation_id=first["invocation_id"],
        input_tokens=24,
        output_tokens=8,
        provider_request_id="provider-request-1",
    )
    settle_retry = store.settle_invocation(
        owner_user_id="alice",
        invocation_id=first["invocation_id"],
        input_tokens=24,
        output_tokens=8,
        provider_request_id="provider-request-1",
    )
    assert settle_retry == settled
    with pytest.raises(ValueError, match="settlement conflicts"):
        store.settle_invocation(
            owner_user_id="alice",
            invocation_id=first["invocation_id"],
            input_tokens=25,
            output_tokens=8,
            provider_request_id="provider-request-1",
        )


def test_graph_schema_rejects_legacy_protocol_without_recreating_tables(
    tmp_path,
    monkeypatch,
) -> None:
    graph_db = tmp_path / "graphs.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", graph_db)
    agent_flow.clear_store_cache()
    research_graphs.ensure_schema()

    with pytest.raises(RuntimeError, match="deprecated split reservation"):
        research_graphs.reserve_tokens(
            owner_user_id="alice",
            scope_id="research-agent-1",
            work_kind="reviewer",
            max_input_tokens=60,
            max_output_tokens=20,
        )

    with connect_sqlite(graph_db) as conn:
        graph_tables = {
            str(row["name"])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert not graph_tables.intersection(
        {
            "research_agent_executions",
            "research_token_budgets",
            "research_token_reservations",
            "research_provider_usage_receipts",
        }
    )
    with connect_sqlite(agent_flow.database_path()) as conn:
        agent_flow_tables = {
            str(row["name"])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert agent_flow_tables == {
        "agent_budget_periods",
        "agent_invocations",
    }


@pytest.mark.parametrize(
    "path",
    [
        "/api/research-agent-executions",
        "/api/research-token-budgets",
        "/api/research-token-budgets/legacy-scope/reserve",
        "/api/research-provider-usage-receipts",
        "/api/research-token-reservations/legacy-id/commit",
        "/api/research-token-reservations/legacy-id/release",
    ],
)
def test_legacy_agent_accounting_http_endpoints_are_explicitly_retired(
    client,
    path,
) -> None:
    response = client.post(path, json={})
    assert response.status_code == 410
    assert response.get_json()["replacement"] == "/api/agent-flow"
