from __future__ import annotations

import orjson
import pytest
from flask import Flask

import settings as Settings
from server.modules.single_factor_test import sft_bp
from server.services import agent_flow, research_graphs
from server.services import research_configurations
from server.services.agent_flow import (
    AgentFlowStore,
    migrate_legacy_graph_accounting,
)
from server.services.agent_flow.verified_usage import (
    VerifiedProviderUsage,
    clear_usage_receipt_verifiers,
    register_usage_receipt_verifier,
)
from server.services.agent_flow import authorization
from server.services.agent_flow import invocations as invocation_module
from server.services.agent_flow import queries as query_module
from server.services.maintenance_cases import MaintenanceCaseStore
from tests.server.data_contract_fixtures import checkpoint, initialize
from tools.data.sqlite.db import connect_sqlite


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(
        Settings,
        "CACHE_DB_PATH",
        tmp_path / "graphs.sqlite",
    )
    agent_flow.clear_store_cache()
    clear_usage_receipt_verifiers()
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "alice"
    return client


def test_public_settlement_is_caller_reported_without_verified_receipt(
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
    assert settled["measurement_quality"] == "caller_reported"
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


def test_server_verified_receipt_can_settle_provider_actual(tmp_path) -> None:
    store = AgentFlowStore(tmp_path / "agent-flow.sqlite")
    invocation = store.reserve_invocation(
        owner_user_id="alice",
        agent_id="research-agent-1",
        actor_role="research",
        authority_scope="local_research",
        purpose="compare one frozen workload",
        runtime_id="runtime-a",
        model_id="model-a",
        max_input_tokens=100,
        max_output_tokens=40,
        agent_principal_hash="a" * 64,
        lineage_hash="b" * 64,
        input_hash="c" * 64,
    )

    class Verifier:
        def verify(self, receipt, *, reservation):
            assert receipt == "opaque-signed-receipt"
            assert reservation["input_hash"] == "c" * 64
            return VerifiedProviderUsage(
                provider_id="provider-a",
                provider_request_id="request-a",
                input_tokens=24,
                output_tokens=8,
                cache_read_tokens=5,
                provider_attestation="provider-signature",
                launcher_attestation="verified-by:test-verifier@1",
            )

    settled = store.settle_verified_invocation(
        owner_user_id="alice",
        invocation_id=invocation["invocation_id"],
        receipt="opaque-signed-receipt",
        expected_provider_id="provider-a",
        verifier=Verifier(),
    )

    assert settled["measurement_quality"] == "provider_actual"
    stored = store.load_invocation(
        owner_user_id="alice",
        invocation_id=invocation["invocation_id"],
    )
    assert stored["provider_id"] == "provider-a"
    assert stored["provider_request_hash"]
    assert stored["provider_attestation_hash"]
    assert stored["launcher_attestation_hash"]


def test_verified_receipt_rejects_provider_identity_mismatch(tmp_path) -> None:
    store = AgentFlowStore(tmp_path / "agent-flow.sqlite")
    invocation = store.reserve_invocation(
        owner_user_id="alice",
        agent_id="research-agent-1",
        actor_role="research",
        authority_scope="local_research",
        purpose="verify provider identity",
        runtime_id="runtime-a",
        model_id="model-a",
        max_input_tokens=100,
        max_output_tokens=40,
        agent_principal_hash="a" * 64,
        lineage_hash="b" * 64,
    )

    class WrongProviderVerifier:
        def verify(self, receipt, *, reservation):
            return VerifiedProviderUsage(
                provider_id="provider-b",
                provider_request_id="request-b",
                input_tokens=24,
                output_tokens=8,
                cache_read_tokens=0,
                provider_attestation="provider-signature",
                launcher_attestation="verified-by:test-verifier@1",
            )

    with pytest.raises(ValueError, match="selected verifier"):
        store.settle_verified_invocation(
            owner_user_id="alice",
            invocation_id=invocation["invocation_id"],
            receipt="opaque-signed-receipt",
            expected_provider_id="provider-a",
            verifier=WrongProviderVerifier(),
        )
    stored = store.load_invocation(
        owner_user_id="alice",
        invocation_id=invocation["invocation_id"],
    )
    assert stored["status"] == "reserved"


def test_http_settlement_uses_registered_provider_verifier(client) -> None:
    class Verifier:
        def verify(self, receipt, *, reservation):
            assert receipt == "opaque-provider-receipt"
            return VerifiedProviderUsage(
                provider_id="provider-a",
                provider_request_id="request-a",
                input_tokens=24,
                output_tokens=8,
                cache_read_tokens=5,
                provider_attestation="provider-signature",
                launcher_attestation="verified-by:http-test@1",
            )

    register_usage_receipt_verifier("provider-a", Verifier())
    reserved = client.post("/api/agent-flow/invocations", json={
        "agent_id": "research-agent-1",
        "actor_role": "researcher",
        "authority_scope": "local_research",
        "purpose": "verify provider usage over HTTP",
        "runtime_id": "runtime-a",
        "model_id": "model-a",
        "max_input_tokens": 100,
        "max_output_tokens": 40,
        "agent_principal_hash": "a" * 64,
        "lineage_hash": "b" * 64,
    })
    assert reserved.status_code == 201
    invocation_id = reserved.get_json()["invocation"]["invocation_id"]
    settled = client.post(
        f"/api/agent-flow/invocations/{invocation_id}/settle",
        json={
            "provider_id": "provider-a",
            "provider_receipt": "opaque-provider-receipt",
        },
    )

    assert settled.status_code == 200
    assert (
        settled.get_json()["invocation"]["measurement_quality"]
        == "provider_actual"
    )


def test_same_agent_continues_after_runtime_and_model_switch(
    tmp_path,
) -> None:
    database_path = tmp_path / "agent-flow.sqlite"
    first_store = AgentFlowStore(database_path)
    first_store.configure_token_limit(
        owner_user_id="alice",
        agent_id="research-agent-1",
        token_limit=200,
    )
    first = first_store.reserve_invocation(
        owner_user_id="alice",
        agent_id="research-agent-1",
        actor_role="research",
        authority_scope="local_research",
        purpose="first runtime",
        runtime_id="runtime-a",
        model_id="model-a",
        max_input_tokens=40,
        max_output_tokens=10,
        agent_principal_hash="a" * 64,
        lineage_hash="b" * 64,
    )
    first_store.settle_invocation(
        owner_user_id="alice",
        invocation_id=first["invocation_id"],
        input_tokens=20,
        output_tokens=5,
    )

    restarted_store = AgentFlowStore(database_path)
    second = restarted_store.reserve_invocation(
        owner_user_id="alice",
        agent_id="research-agent-1",
        actor_role="research",
        authority_scope="local_research",
        purpose="continue after runtime switch",
        runtime_id="runtime-b",
        model_id="model-b",
        max_input_tokens=30,
        max_output_tokens=10,
        agent_principal_hash="a" * 64,
        lineage_hash="b" * 64,
    )
    restarted_store.settle_invocation(
        owner_user_id="alice",
        invocation_id=second["invocation_id"],
        input_tokens=12,
        output_tokens=3,
    )

    period = restarted_store.load_current_budget_period(
        owner_user_id="alice",
        agent_id="research-agent-1",
    )
    invocations = restarted_store.load_invocations(
        owner_user_id="alice",
        invocation_ids=[
            first["invocation_id"],
            second["invocation_id"],
        ],
    )

    assert first["period_id"] == second["period_id"] == period["period_id"]
    assert period["used_tokens"] == 40
    assert period["reserved_tokens"] == 0
    assert period["available_tokens"] == 160
    assert {
        (
            invocation["runtime_id"],
            invocation["model_id"],
            invocation["status"],
        )
        for invocation in invocations.values()
    } == {
        ("runtime-a", "model-a", "settled"),
        ("runtime-b", "model-b", "settled"),
    }


def test_role_resume_packets_are_bounded_stable_and_isolated(
    tmp_path,
    monkeypatch,
) -> None:
    graph_path = tmp_path / "graphs.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", graph_path)
    agent_flow.clear_store_cache()
    initialize(graph_path, obligation_status="open")
    research_configurations.create_workspace_configuration(
        owner="alice",
        workspace_id="workspace-1",
        factor_families=[{"alias": "alice:SgCCS"}],
    )
    maintenance_case = MaintenanceCaseStore(graph_path).open_case(
        owner_user_id="alice",
        kind="capability_gap",
        descriptor_hash="a" * 64,
        affected_refs=["workspace:workspace-1"],
        change_refs=[],
    )
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "alice"

    research = client.post(
        "/api/agent-flow/agents/research-agent-1/resume",
        json={
            "role": "research",
            "instance_id": "instance-1",
            "branch_id": "branch-1",
        },
    ).get_json()["resume"]
    with connect_sqlite(graph_path) as connection:
        before_graph_counts = tuple(
            connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            for table in (
                "research_graph_trace",
                "research_maintenance_cases",
                "research_configurations",
            )
        )
    with connect_sqlite(agent_flow.database_path()) as connection:
        before_flow_counts = tuple(
            connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            for table in ("agent_budget_periods", "agent_invocations")
        )
    repeated = client.post(
        "/api/agent-flow/agents/research-agent-1/resume",
        json={
            "role": "research",
            "instance_id": "instance-1",
            "branch_id": "branch-1",
        },
    ).get_json()["resume"]
    with connect_sqlite(graph_path) as connection:
        after_graph_counts = tuple(
            connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            for table in (
                "research_graph_trace",
                "research_maintenance_cases",
                "research_configurations",
            )
        )
    with connect_sqlite(agent_flow.database_path()) as connection:
        after_flow_counts = tuple(
            connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            for table in ("agent_budget_periods", "agent_invocations")
        )
    planning = client.post(
        "/api/agent-flow/agents/planning-agent-1/resume",
        json={
            "role": "planning",
            "workspace_id": "workspace-1",
        },
    ).get_json()["resume"]
    monkeypatch.setattr(
        authorization,
        "get_account",
        lambda _username: {"username": "alice", "role": "developer"},
    )
    maintenance = client.post(
        "/api/agent-flow/agents/server-agent-1/resume",
        json={"role": "server_maintenance"},
    ).get_json()["resume"]

    assert research == repeated
    assert after_graph_counts == before_graph_counts
    assert after_flow_counts == before_flow_counts
    assert research["packet_bytes"] <= 6000
    assert research["agent"]["budget"]["configured"] is False
    assert research["research"]["node"]["node_id"] == "data_contract"
    assert [
        item["obligation_id"]
        for item in research["research"]["current_obligations"]
    ] == ["obligation-data"]
    assert "planning" not in research
    assert "maintenance" not in research

    assert planning["packet_bytes"] <= 6000
    assert planning["planning"]["workspace_id"] == "workspace-1"
    assert planning["planning"]["factor_summary"] == {
        "configuration_id": planning["planning"]["factor_summary"][
            "configuration_id"
        ],
        "revision": 1,
        "fingerprint": planning["planning"]["factor_summary"][
            "fingerprint"
        ],
        "family_count": 1,
        "factor_count": 0,
        "family_refs": ["alice:SgCCS"],
        "omitted_family_count": 0,
    }
    assert "research" not in planning
    assert "maintenance" not in planning

    assert maintenance["packet_bytes"] <= 6000
    assert maintenance["maintenance"]["cases"] == [{
        "case_id": maintenance_case["case_id"],
        "kind": "capability_gap",
        "status": "open",
        "descriptor_hash": "a" * 64,
        "affected_refs": ["workspace:workspace-1"],
        "remaining_affected_ref_count": 0,
        "change_refs": [],
        "remaining_change_ref_count": 0,
        "claimed_agent_id": "",
    }]
    assert "research" not in maintenance
    assert "planning" not in maintenance


def test_research_resume_keeps_many_obligations_lazy_and_bounded(
    tmp_path,
    monkeypatch,
) -> None:
    graph_path = tmp_path / "graphs.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", graph_path)
    agent_flow.clear_store_cache()
    initialize(graph_path, obligation_status="open")
    cycle = checkpoint(obligation_status="open")
    template = cycle["obligations"][0]
    cycle["obligations"] = [
        {
            **template,
            "obligation_id": f"obligation-{index}",
            "epistemic_question": (
                f"第 {index} 项研究义务是否能够由当前证据解除，"
                "还是需要按引用加载完整语义、范围与判定标准？"
            ),
            "created_event_ref": f"trace:obligation-{index}",
        }
        for index in range(8)
    ]
    cycle.pop("projection_hash", None)
    from server.services.research_graph.research_cycle.replay import (
        validate_research_cycle_checkpoint,
    )

    cycle = validate_research_cycle_checkpoint(cycle)
    with connect_sqlite(graph_path) as connection:
        evidence = {
            "research_cycle_checkpoint": cycle,
            "evidence_refs": [],
        }
        connection.execute(
            """
            UPDATE research_graph_trace SET evidence_json=?
            WHERE trace_id='trace-bootstrap'
            """,
            (orjson.dumps(evidence).decode(),),
        )

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "alice"

    response = client.post(
        "/api/agent-flow/agents/research-agent-1/resume",
        json={
            "role": "research",
            "instance_id": "instance-1",
            "branch_id": "branch-1",
        },
    )

    assert response.status_code == 200
    resume = response.get_json()["resume"]
    assert resume["packet_bytes"] <= 6000
    obligations = resume["research"]["current_obligations"]
    assert [item["obligation_id"] for item in obligations] == [
        f"obligation-{index}" for index in range(8)
    ]
    assert all(item["question_summary"] for item in obligations)
    assert all(item["detail_ref"] for item in obligations)
    assert all("claim_ids" not in item for item in obligations)
    assert all("criterion_ref" not in item for item in obligations)
    frontier = resume["research"]["candidate_trial_frontier"]
    assert frontier["unassessed_obligation_count"] == 8
    assert "unassessed_obligation_ids" not in frontier


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


def test_shadow_cohort_uses_one_bounded_read(tmp_path, monkeypatch) -> None:
    store = AgentFlowStore(tmp_path / "agent-flow.sqlite")
    statements: list[str] = []
    connect = query_module.connect_agent_flow

    def traced_connect(db_path):
        connection = connect(db_path)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(query_module, "connect_agent_flow", traced_connect)
    assert store.load_shadow_token_cohort(
        owner_user_id="alice",
        lineage_hash="b" * 64,
    ) == []
    reads = [
        statement.strip().upper()
        for statement in statements
        if statement.strip().upper().startswith("SELECT")
    ]
    assert len(reads) == 1
    assert "OWNER_USER_ID=" in reads[0]
    assert "LINEAGE_HASH=" in reads[0]
    assert "LIMIT 3" in reads[0]


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

    assert report["budget_periods_migrated"] == 1
    assert report["invocations_migrated"] == 1
    assert report["legacy_tables_dropped"] == 4
    assert report["sql_transactions"] == 1
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
    assert "legacy_reservation_id" not in invocation
    assert "legacy_provider_receipt_id" not in invocation
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
    assert "legacy_reservation_id" not in invocation
    assert "legacy_provider_receipt_id" not in invocation

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
    settled_payload = settle_response.get_json()["invocation"]
    assert settled_payload["charged_tokens"] == 32
    assert "legacy_reservation_id" not in settled_payload
    assert "legacy_provider_receipt_id" not in settled_payload


def test_http_rejects_client_claimed_backend_authority(
    client,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        authorization,
        "get_account",
        lambda _username: {"username": "alice", "role": "user"},
    )

    response = client.post(
        "/api/agent-flow/invocations",
        json={
            "agent_id": "forged-backend-agent",
            "actor_role": "backend_verifier",
            "authority_scope": "server_backend_code",
            "purpose": "claim backend authority",
            "runtime_id": "runtime-a",
            "model_id": "model-a",
            "max_input_tokens": 100,
            "max_output_tokens": 40,
            "agent_principal_hash": "a" * 64,
            "lineage_hash": "b" * 64,
        },
    )

    assert response.status_code == 403
    assert "developer account" in response.get_json()["error"]


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


def test_graph_schema_does_not_recreate_legacy_accounting_tables(
    tmp_path,
    monkeypatch,
) -> None:
    graph_db = tmp_path / "graphs.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", graph_db)
    agent_flow.clear_store_cache()
    research_graphs.ensure_schema()

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
def test_legacy_agent_accounting_http_endpoints_are_absent(
    client,
    path,
) -> None:
    response = client.post(path, json={})
    assert response.status_code == 404
