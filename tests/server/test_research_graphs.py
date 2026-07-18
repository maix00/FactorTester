from __future__ import annotations

from copy import deepcopy
import hashlib
import hmac
import json
import os
import time
import uuid

from flask import Flask
import orjson
import pytest

import settings as Settings
from server.modules.single_factor_test import sft_bp
from server.services import research_graphs, research_runs


def _initialize_graph_db(tmp_path, monkeypatch) -> None:
    """Run graph migrations explicitly before exercising request hot paths."""
    monkeypatch.setattr(
        Settings,
        "CACHE_DB_PATH",
        tmp_path / "graphs.sqlite",
    )
    research_graphs.ensure_schema()
    monkeypatch.setenv(
        "RESEARCH_AGENT_LAUNCHER_SECRET",
        "test-agent-launcher-secret",
    )
    monkeypatch.setenv(
        "RESEARCH_HUMAN_ACTIVATION_SECRET",
        "test-human-activation-secret",
    )


def _hash(graph: dict) -> str:
    payload = deepcopy(graph)
    payload.pop("content_hash", None)
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def _descriptor(capability_id: str) -> dict:
    return {
        "capability_description": f"Test contract for {capability_id}.",
        "descriptor_hash": hashlib.sha256(
            capability_id.encode()
        ).hexdigest(),
    }


def _approve_proposal(
    version: int = 2,
    new_hash: str | None = None,
) -> tuple[dict, dict]:
    proposer = _agent_execution("proposer")
    reviewer = _agent_execution("reviewer")
    proposal = research_graphs.record_proposal(
        graph_id="factor-research",
        version=version,
        owner_user_id="alice",
        actor_agent_id=proposer["execution_id"],
        risk_level="L4",
        change_diff={
            "old_hash": "observed",
            "new_hash": new_hash or _draft_graph()["content_hash"],
            "reason": "activate reviewed adaptive research semantics",
            "rollback_target": 1,
        },
        evidence_refs=["test:proposal"],
        token_estimate=500,
    )
    review = research_graphs.record_proposal_review(
        proposal_id=proposal["proposal_id"],
        owner_user_id="alice",
        actor_agent_id=reviewer["execution_id"],
        disposition="approved",
        scope_drift=False,
        semantic_uncertainty=False,
        evidence_refs=["test:independent-review"],
    )
    return proposal, review


def _create_attested_agent(
    role: str,
    reservation_id: str,
    *,
    principal_label: str | None = None,
    lineage_label: str | None = None,
    model_id: str = "test-model",
) -> dict:
    principal_hash = hashlib.sha256(
        (principal_label or uuid.uuid4().hex).encode()
    ).hexdigest()
    lineage_hash = hashlib.sha256(
        (lineage_label or uuid.uuid4().hex).encode()
    ).hexdigest()
    payload = {
        "owner_user_id": "alice",
        "actor_role": role,
        "model_id": model_id,
        "codex_version": "",
        "reservation_id": reservation_id,
        "agent_principal_hash": principal_hash,
        "lineage_hash": lineage_hash,
    }
    attestation = hmac.new(
        b"test-agent-launcher-secret",
        orjson.dumps(payload, option=orjson.OPT_SORT_KEYS),
        hashlib.sha256,
    ).hexdigest()
    return research_graphs.create_agent_execution(
        **payload,
        launcher_attestation=attestation,
    )


def _agent_execution(
    role: str,
    *,
    principal_label: str | None = None,
    lineage_label: str | None = None,
) -> dict:
    scope_id = f"test:{role}:{uuid.uuid4().hex}"
    research_graphs.create_token_budget(
        owner_user_id="alice",
        scope_id=scope_id,
        token_limit=1000,
    )
    reservation = research_graphs.reserve_tokens(
        owner_user_id="alice",
        scope_id=scope_id,
        work_kind=role,
        max_input_tokens=400,
        max_output_tokens=200,
    )
    return _create_attested_agent(
        role,
        reservation_id=reservation["reservation_id"],
        principal_label=principal_label,
        lineage_label=lineage_label,
    )


def _agent_http_payload(
    role: str,
    reservation_id: str,
    *,
    model_id: str,
) -> dict:
    principal_hash = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    lineage_hash = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    payload = {
        "owner_user_id": "alice",
        "actor_role": role,
        "model_id": model_id,
        "codex_version": "",
        "reservation_id": reservation_id,
        "agent_principal_hash": principal_hash,
        "lineage_hash": lineage_hash,
    }
    payload["launcher_attestation"] = hmac.new(
        b"test-agent-launcher-secret",
        orjson.dumps(payload, option=orjson.OPT_SORT_KEYS),
        hashlib.sha256,
    ).hexdigest()
    payload.pop("owner_user_id")
    return payload


def _human_authorization(
    *,
    graph_version: int = 2,
    owner_user_id: str = "alice",
) -> dict:
    graph = research_graphs.load_graph(
        graph_id="factor-research",
        version=graph_version,
    )
    with research_graphs.connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        proposal = conn.execute(
            """
            SELECT * FROM research_graph_proposals
            WHERE graph_id='factor-research' AND version=?
            ORDER BY created_at DESC, proposal_id DESC LIMIT 1
            """,
            (graph_version,),
        ).fetchone()
    change_diff = orjson.loads(proposal["change_diff_json"])
    diff_hash = hashlib.sha256(
        orjson.dumps(change_diff, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()
    nonce = uuid.uuid4().hex
    expires_at = time.time() + 300
    payload = {
        "owner_user_id": owner_user_id,
        "graph_id": "factor-research",
        "graph_version": graph_version,
        "graph_hash": graph["content_hash"],
        "proposal_id": proposal["proposal_id"],
        "diff_hash": diff_hash,
        "nonce_hash": hashlib.sha256(nonce.encode()).hexdigest(),
        "authorized_by": "human-auditor",
        "expires_at": expires_at,
    }
    attestation = hmac.new(
        b"test-human-activation-secret",
        orjson.dumps(payload, option=orjson.OPT_SORT_KEYS),
        hashlib.sha256,
    ).hexdigest()
    return research_graphs.authorize_graph_activation(
        owner_user_id=owner_user_id,
        graph_id="factor-research",
        graph_version=graph_version,
        proposal_id=proposal["proposal_id"],
        graph_hash=graph["content_hash"],
        diff_hash=diff_hash,
        nonce=nonce,
        authorized_by="human-auditor",
        expires_at=expires_at,
        human_attestation=attestation,
    )


def _activate(graph_version: int = 2) -> dict:
    authorization = _human_authorization(graph_version=graph_version)
    return research_graphs.activate_graph(
        graph_id="factor-research",
        source_version=graph_version,
        actor="alice",
        human_authorization_id=authorization["authorization_id"],
    )


def _issue_receipt(
    *,
    node_id: str,
    product_group: str,
    capability_ids: list[str],
    triggered_capability_ids: list[str] | None = None,
    undetermined_conditions: list[dict] | None = None,
    graph_version: int | None = None,
    shadow_mode: bool = False,
) -> dict:
    active = (
        research_graphs.load_graph(
            graph_id="factor-research",
            version=graph_version,
        )
        if graph_version is not None
        else research_graphs.load_active_graph(
            graph_id="factor-research"
        )
    )
    approval_refs = {}
    bindings = []
    triggered_bindings = []
    triggered_ids = set(triggered_capability_ids or [])
    for capability_id in capability_ids:
        descriptor = active["capability_descriptors"][capability_id]
        approval = research_graphs.record_capability_approval(
            owner_user_id="alice",
            capability_id=capability_id,
            descriptor_hash=descriptor["descriptor_hash"],
            product_group=product_group,
            actor="alice",
            evidence_refs=[f"audit:capability:{capability_id}"],
        )
        approval_refs[capability_id] = approval["approval_id"]
        target = (
            triggered_bindings
            if capability_id in triggered_ids
            else bindings
        )
        target.append({
            "capability_id": capability_id,
            **descriptor,
        })
    return research_graphs.issue_capability_receipt(
        owner_user_id="alice",
        graph_id="factor-research",
        graph_version=active["version"],
        node_id=node_id,
        product_group=product_group,
        catalog_hash="c" * 64,
        product_profile_hash="d" * 64,
        resolver_version="test-resolver-v1",
        semantic_resolution={
            "node_id": node_id,
            "bindings": bindings,
            "gaps": [],
            "triggered_conditional_bindings": triggered_bindings,
            "undetermined_conditions": undetermined_conditions or [],
        },
        approval_refs=approval_refs,
        provider_conformance_hash="e" * 64,
        shadow_mode=shadow_mode,
    )


def _commit_scope_usage(
    *,
    scope_id: str,
    input_tokens: int,
    output_tokens: int,
) -> str:
    secret = "test-provider-secret"
    os.environ["RESEARCH_PROVIDER_USAGE_SECRET"] = secret
    reservation = research_graphs.reserve_tokens(
        owner_user_id="alice",
        scope_id=scope_id,
        work_kind="researcher",
        max_input_tokens=input_tokens,
        max_output_tokens=output_tokens,
    )
    payload = {
        "reservation_id": reservation["reservation_id"],
        "provider": "test-provider",
        "provider_request_id": uuid.uuid4().hex,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
    signature = hmac.new(
        secret.encode(),
        orjson.dumps(payload, option=orjson.OPT_SORT_KEYS),
        hashlib.sha256,
    ).hexdigest()
    receipt = research_graphs.ingest_provider_usage_receipt(
        **payload,
        usage_attestation=signature,
    )
    research_graphs.commit_token_reservation(
        owner_user_id="alice",
        reservation_id=reservation["reservation_id"],
        provider_receipt_id=receipt["provider_receipt_id"],
    )
    return reservation["reservation_id"]


def _commit_usage(
    *,
    instance_id: str,
    input_tokens: int,
    output_tokens: int,
) -> str:
    return _commit_scope_usage(
        scope_id=f"instance:{instance_id}",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _server_validation_evidence(
    *,
    version: int = 2,
    shadow_passed: bool = True,
    graph_tokens: int = 80,
    baseline_tokens: int = 100,
    matching_run_spec: bool = True,
    launch_subagent: bool = False,
) -> dict:
    workspace_id = f"shadow-workspace-{uuid.uuid4().hex}"
    run_spec = {
        "workspace_id": workspace_id,
        "factor": "test-factor",
        "window": ["2020-01-01", "2024-12-31"],
    }
    graph_run = research_runs.create_run(
        owner="alice",
        workspace_id=workspace_id,
        configuration_id=f"graph-{uuid.uuid4().hex}",
        configuration_revision=1,
        run_spec=run_spec,
    )
    baseline_run = research_runs.create_run(
        owner="alice",
        workspace_id=workspace_id,
        configuration_id=f"baseline-{uuid.uuid4().hex}",
        configuration_revision=1,
        run_spec=(
            run_spec
            if matching_run_spec
            else {**run_spec, "factor": "different-factor"}
        ),
    )
    receipt = _issue_receipt(
        node_id="hypothesis",
        product_group="equities",
        capability_ids=["research-hypothesis.preregister"],
        graph_version=version,
        shadow_mode=True,
    )
    instance = research_graphs.create_graph_instance(
        graph_id="factor-research",
        owner="alice",
        product_group="equities",
        workspace_id=workspace_id,
        token_budget=1000,
        capability_receipt=receipt,
        shadow_graph_version=version,
        shadow_run_id=graph_run["run_id"],
    )
    if graph_tokens:
        _commit_usage(
            instance_id=instance["instance_id"],
            input_tokens=max(graph_tokens - 10, 0),
            output_tokens=min(graph_tokens, 10),
        )
    if launch_subagent:
        reservation = research_graphs.reserve_tokens(
            owner_user_id="alice",
            scope_id=f"instance:{instance['instance_id']}",
            work_kind="reviewer",
            max_input_tokens=10,
            max_output_tokens=5,
        )
        _create_attested_agent(
            "reviewer",
            reservation_id=reservation["reservation_id"],
        )
    baseline_scope_id = f"research-run:{baseline_run['run_id']}"
    research_graphs.create_token_budget(
        owner_user_id="alice",
        scope_id=baseline_scope_id,
        token_limit=1000,
    )
    if baseline_tokens:
        _commit_scope_usage(
            scope_id=baseline_scope_id,
            input_tokens=max(baseline_tokens - 10, 0),
            output_tokens=min(baseline_tokens, 10),
        )
    return {
        "replay_passed": True,
        "shadow_passed": shadow_passed,
        "capability_resolution_complete": True,
        "unaffected_jobs_preserved": True,
        "token_efficiency_passed": True,
        "token_measurement_refs": {
            "routine_instance_id": instance["instance_id"],
            "routine_branch_id": instance["branches"][0]["branch_id"],
            "baseline_run_id": baseline_run["run_id"],
        },
    }


def _draft_graph() -> dict:
    graph = {
        "schema_version": 1,
        "graph_id": "factor-research",
        "version": 2,
        "lifecycle": "draft",
        "parent_version": 1,
        "research_semantics": "product_neutral",
        "nodes": [{
            "node_id": "hypothesis",
            "kind": "research",
            "purpose": "freeze hypothesis",
            "enforcement": "audited",
            "required_capabilities": ["research-hypothesis.preregister"],
            "entry_evidence": [],
            "exit_evidence": [],
        }],
        "edges": [],
        "capability_descriptors": {
            "research-hypothesis.preregister": _descriptor(
                "research-hypothesis.preregister"
            ),
        },
        "provenance": {"source": "test"},
    }
    graph["content_hash"] = _hash(graph)
    return graph


@pytest.fixture()
def client(tmp_path, monkeypatch):
    _initialize_graph_db(tmp_path, monkeypatch)
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "alice"
    return client


def test_graph_versions_are_immutable_and_activation_creates_a_new_version(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    draft = research_graphs.register_graph(_draft_graph(), actor="curator-agent")

    changed = _draft_graph()
    changed["nodes"][0]["purpose"] = "changed"
    changed["content_hash"] = _hash(changed)
    with pytest.raises(research_graphs.GraphVersionConflict):
        research_graphs.register_graph(changed, actor="curator-agent")

    _approve_proposal()
    validation = research_graphs.record_validation(
        graph_id="factor-research",
        version=2,
        actor="review-agent",
        evidence=_server_validation_evidence(),
    )
    metrics = validation["evidence"]["token_metrics"]
    assert validation["evidence"]["token_metrics_authority"] == "server_derived"
    assert metrics["shadow_graph_total_tokens"] == 80
    assert metrics["shadow_baseline_total_tokens"] == 100
    assert metrics["routine_context_bytes"] > 0
    assert metrics["run_spec_hash"]
    research_graphs.record_audit(
        graph_id="factor-research",
        version=2,
        actor="human-auditor",
        disposition="approved",
        grill_evidence=[
            {"question": "Can holdout select?", "answer": "No", "status": "pass"}
        ],
    )
    active = _activate()

    assert draft["lifecycle"] == "draft"
    assert active["version"] == 3
    assert active["lifecycle"] == "active"
    assert active["parent_version"] == 2
    assert research_graphs.load_active_graph(
        graph_id="factor-research"
    )["content_hash"] == active["content_hash"]


def test_agent_execution_rejects_forged_launcher_attestation(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    scope_id = "test:forged-launcher"
    research_graphs.create_token_budget(
        owner_user_id="alice",
        scope_id=scope_id,
        token_limit=1000,
    )
    reservation = research_graphs.reserve_tokens(
        owner_user_id="alice",
        scope_id=scope_id,
        work_kind="proposer",
        max_input_tokens=400,
        max_output_tokens=200,
    )

    with pytest.raises(ValueError, match="launcher attestation is invalid"):
        research_graphs.create_agent_execution(
            owner_user_id="alice",
            actor_role="proposer",
            reservation_id=reservation["reservation_id"],
            agent_principal_hash="a" * 64,
            lineage_hash="b" * 64,
            launcher_attestation="forged",
        )


@pytest.mark.parametrize(
    ("principal_label", "lineage_label"),
    [
        ("same-principal", None),
        (None, "same-lineage"),
    ],
)
def test_proposal_review_requires_independent_principal_and_lineage(
    tmp_path,
    monkeypatch,
    principal_label,
    lineage_label,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    research_graphs.register_graph(_draft_graph(), actor="curator-agent")
    proposer = _agent_execution(
        "proposer",
        principal_label=principal_label,
        lineage_label=lineage_label,
    )
    proposal = research_graphs.record_proposal(
        graph_id="factor-research",
        version=2,
        owner_user_id="alice",
        actor_agent_id=proposer["execution_id"],
        risk_level="L4",
        change_diff={"reason": "test independent review"},
        evidence_refs=["test:independence"],
        token_estimate=100,
    )
    reviewer = _agent_execution(
        "reviewer",
        principal_label=principal_label,
        lineage_label=lineage_label,
    )

    with pytest.raises(ValueError, match="principal and lineage"):
        research_graphs.record_proposal_review(
            proposal_id=proposal["proposal_id"],
            owner_user_id="alice",
            actor_agent_id=reviewer["execution_id"],
            disposition="approved",
            scope_drift=False,
            semantic_uncertainty=False,
            evidence_refs=["test:must-reject"],
        )


def test_activation_requires_exact_one_time_human_authorization(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    research_graphs.register_graph(_draft_graph(), actor="curator-agent")
    _approve_proposal()
    research_graphs.record_validation(
        graph_id="factor-research",
        version=2,
        actor="validation-agent",
        evidence=_server_validation_evidence(),
    )
    research_graphs.record_audit(
        graph_id="factor-research",
        version=2,
        actor="human-auditor",
        disposition="approved",
        grill_evidence=[{"question": "activate?", "answer": "yes"}],
    )

    with pytest.raises(
        research_graphs.GraphActivationBlocked,
        match="human activation authorization",
    ):
        research_graphs.activate_graph(
            graph_id="factor-research",
            source_version=2,
            actor="alice",
            human_authorization_id="missing",
        )

    authorization = _human_authorization()
    active = research_graphs.activate_graph(
        graph_id="factor-research",
        source_version=2,
        actor="alice",
        human_authorization_id=authorization["authorization_id"],
    )
    assert active["lifecycle"] == "active"
    with research_graphs.connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        consumed_at = conn.execute(
            """
            SELECT consumed_at FROM human_activation_authorizations
            WHERE authorization_id=?
            """,
            (authorization["authorization_id"],),
        ).fetchone()["consumed_at"]
    assert consumed_at is not None


def test_human_authorization_rejects_forged_adapter_attestation(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    research_graphs.register_graph(_draft_graph(), actor="curator-agent")
    proposal, _ = _approve_proposal()
    graph = research_graphs.load_graph(
        graph_id="factor-research",
        version=2,
    )
    diff_hash = hashlib.sha256(orjson.dumps(
        proposal["change_diff"],
        option=orjson.OPT_SORT_KEYS,
    )).hexdigest()

    with pytest.raises(ValueError, match="attestation is invalid"):
        research_graphs.authorize_graph_activation(
            owner_user_id="alice",
            graph_id="factor-research",
            graph_version=2,
            proposal_id=proposal["proposal_id"],
            graph_hash=graph["content_hash"],
            diff_hash=diff_hash,
            nonce=uuid.uuid4().hex,
            authorized_by="ordinary-authenticated-session",
            expires_at=time.time() + 300,
            human_attestation="forged",
        )


def test_graph_request_paths_do_not_run_schema_ddl(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    statements: list[str] = []
    original_connect = research_graphs.connect_sqlite

    def traced_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(research_graphs, "connect_sqlite", traced_connect)

    research_graphs.register_graph(_draft_graph(), actor="curator-agent")
    assert research_graphs.load_graph(
        graph_id="factor-research",
        version=2,
    ) is not None
    assert len(research_graphs.list_graph_versions(
        graph_id="factor-research",
    )) == 1
    research_graphs.create_token_budget(
        owner_user_id="alice",
        scope_id="request-hot-path",
        token_limit=100,
    )

    normalized = [statement.strip().upper() for statement in statements]
    assert not any(
        statement.startswith(("CREATE ", "ALTER ", "DROP "))
        for statement in normalized
    )
    assert not any(
        statement.startswith("PRAGMA TABLE_INFO")
        for statement in normalized
    )
    with original_connect(Settings.CACHE_DB_PATH) as connection:
        index_names = {
            str(row["name"])
            for row in connection.execute(
                "PRAGMA index_list(research_graph_node_resolutions)"
            ).fetchall()
        }
    assert "idx_research_graph_node_resolutions_branch" not in index_names


def test_immutable_graph_cache_uses_hash_and_returns_defensive_copies(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    stored = research_graphs.register_graph(
        _draft_graph(),
        actor="curator-agent",
    )
    stored["nodes"][0]["purpose"] = "caller mutation"
    statements: list[str] = []
    original_connect = research_graphs.connect_sqlite

    def traced_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(research_graphs, "connect_sqlite", traced_connect)
    cached = research_graphs.load_graph(
        graph_id="factor-research",
        version=2,
    )

    assert cached["nodes"][0]["purpose"] == "freeze hypothesis"
    assert statements == []
    assert any(
        key[1:] == (
            "factor-research",
            2,
            cached["content_hash"],
        )
        for key in research_graphs._GRAPH_CACHE
    )


def test_activation_requires_replay_shadow_capability_and_job_isolation(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    research_graphs.register_graph(_draft_graph(), actor="curator-agent")
    _approve_proposal()
    research_graphs.record_validation(
        graph_id="factor-research",
        version=2,
        actor="review-agent",
        evidence=_server_validation_evidence(shadow_passed=False),
    )
    research_graphs.record_audit(
        graph_id="factor-research",
        version=2,
        actor="human-auditor",
        disposition="approved",
        grill_evidence=[{"question": "Shadow?", "answer": "Pending"}],
    )

    with pytest.raises(research_graphs.GraphActivationBlocked, match="shadow_passed"):
        _activate()


def test_validation_rejects_a_token_efficient_claim_with_regression(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    research_graphs.register_graph(_draft_graph(), actor="curator-agent")

    with pytest.raises(ValueError, match="client token_metrics"):
        research_graphs.record_validation(
            graph_id="factor-research",
            version=2,
            actor="review-agent",
            evidence={
                "token_efficiency_passed": True,
                "token_metrics": {
                    "shadow_graph_total_tokens": 1,
                    "shadow_baseline_total_tokens": 999999,
                },
            },
        )
    with pytest.raises(ValueError, match="token efficiency checks failed"):
        research_graphs.record_validation(
            graph_id="factor-research",
            version=2,
            actor="review-agent",
            evidence=_server_validation_evidence(
                graph_tokens=120,
                baseline_tokens=100,
            ),
        )


@pytest.mark.parametrize(
    ("evidence_kwargs", "message"),
    [
        ({"graph_tokens": 0}, "nonzero"),
        ({"baseline_tokens": 0}, "nonzero"),
        ({"matching_run_spec": False}, "RunSpec hash"),
        ({"launch_subagent": True}, "routine_subagent_count"),
    ],
)
def test_validation_rejects_untrusted_or_noncomparable_shadow_measurements(
    tmp_path,
    monkeypatch,
    evidence_kwargs,
    message,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    research_graphs.register_graph(_draft_graph(), actor="curator-agent")

    with pytest.raises(ValueError, match=message):
        research_graphs.record_validation(
            graph_id="factor-research",
            version=2,
            actor="review-agent",
            evidence=_server_validation_evidence(**evidence_kwargs),
        )


def test_review_disagreement_adds_a_third_reviewer_only_then(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    research_graphs.register_graph(_draft_graph(), actor="curator-agent")
    proposal = research_graphs.record_proposal(
        graph_id="factor-research",
        version=2,
        owner_user_id="alice",
        actor_agent_id=_agent_execution("proposer")["execution_id"],
        risk_level="L4",
        change_diff={"reason": "test disagreement path"},
        evidence_refs=["test:proposal"],
        token_estimate=300,
    )
    research_graphs.record_proposal_review(
        proposal_id=proposal["proposal_id"],
        owner_user_id="alice",
        actor_agent_id=_agent_execution("reviewer")["execution_id"],
        disposition="disagreed",
        scope_drift=False,
        semantic_uncertainty=True,
        evidence_refs=["test:counterexample"],
    )
    research_graphs.record_validation(
        graph_id="factor-research",
        version=2,
        actor="validation-agent",
        evidence=_server_validation_evidence(),
    )
    research_graphs.record_audit(
        graph_id="factor-research",
        version=2,
        actor="human-auditor",
        disposition="approved",
        grill_evidence=[{"question": "counterexample?", "answer": "bounded"}],
    )

    with pytest.raises(
        research_graphs.GraphActivationBlocked,
        match="third reviewer",
    ):
        _activate()

    for reviewer in ("reviewer-2", "reviewer-3"):
        research_graphs.record_proposal_review(
            proposal_id=proposal["proposal_id"],
            owner_user_id="alice",
            actor_agent_id=_agent_execution("reviewer")["execution_id"],
            disposition="approved",
            scope_drift=False,
            semantic_uncertainty=False,
            evidence_refs=[f"test:{reviewer}"],
        )
    active = _activate()
    assert active["lifecycle"] == "active"


def test_audited_rollback_moves_only_the_active_pointer(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    research_graphs.register_graph(_draft_graph(), actor="curator-agent")
    _approve_proposal()
    research_graphs.record_validation(
        graph_id="factor-research",
        version=2,
        actor="validation-agent",
        evidence=_server_validation_evidence(),
    )
    research_graphs.record_audit(
        graph_id="factor-research",
        version=2,
        actor="human-auditor",
        disposition="approved",
        grill_evidence=[{"question": "activate?", "answer": "yes"}],
    )
    first_active = _activate()
    second_draft = _draft_graph()
    second_draft["version"] = 4
    second_draft["parent_version"] = 3
    second_draft["nodes"][0]["purpose"] = "freeze a refined hypothesis"
    second_draft["content_hash"] = _hash(second_draft)
    research_graphs.register_graph(second_draft, actor="curator-agent")
    _approve_proposal(
        version=4,
        new_hash=second_draft["content_hash"],
    )
    research_graphs.record_validation(
        graph_id="factor-research",
        version=4,
        actor="validation-agent",
        evidence=_server_validation_evidence(version=4),
    )
    research_graphs.record_audit(
        graph_id="factor-research",
        version=4,
        actor="human-auditor",
        disposition="approved",
        grill_evidence=[{"question": "activate refined?", "answer": "yes"}],
    )
    second_active = _activate(graph_version=4)

    rollback = research_graphs.rollback_active_graph(
        graph_id="factor-research",
        target_version=first_active["version"],
        actor="human-auditor",
        reason="shadow regression after activation",
        grill_evidence=[{
            "question": "preserve running jobs?",
            "answer": "yes; only move the graph pointer",
        }],
    )

    assert second_active["version"] == 5
    assert rollback["from_version"] == 5
    assert rollback["to_version"] == 3
    assert research_graphs.load_active_graph(
        graph_id="factor-research"
    )["version"] == 3
    assert research_graphs.load_graph(
        graph_id="factor-research",
        version=5,
    )["lifecycle"] == "active"


def test_graph_http_api_persists_validation_and_audit_without_direct_mutation(
    client,
) -> None:
    created = client.post("/api/research-graphs/versions", json={
        "graph": _draft_graph(),
    })
    assert created.status_code == 201
    proposer_scope = f"http:proposer:{uuid.uuid4().hex}"
    reviewer_scope = f"http:reviewer:{uuid.uuid4().hex}"
    for scope in (proposer_scope, reviewer_scope):
        assert client.post("/api/research-token-budgets", json={
            "scope_id": scope,
            "token_limit": 1000,
        }).status_code == 201
    proposer_reservation = client.post(
        f"/api/research-token-budgets/{proposer_scope}/reserve",
        json={
            "work_kind": "proposer",
            "max_input_tokens": 400,
            "max_output_tokens": 200,
        },
    ).get_json()["reservation"]
    reviewer_reservation = client.post(
        f"/api/research-token-budgets/{reviewer_scope}/reserve",
        json={
            "work_kind": "reviewer",
            "max_input_tokens": 400,
            "max_output_tokens": 200,
        },
    ).get_json()["reservation"]
    proposer = client.post(
        "/api/research-agent-executions",
        json=_agent_http_payload(
            "proposer",
            proposer_reservation["reservation_id"],
            model_id="test-proposer",
        ),
    )
    reviewer = client.post(
        "/api/research-agent-executions",
        json=_agent_http_payload(
            "reviewer",
            reviewer_reservation["reservation_id"],
            model_id="test-reviewer",
        ),
    )
    assert proposer.status_code == 201
    assert reviewer.status_code == 201
    proposal = client.post(
        "/api/research-graphs/factor-research/versions/2/proposals",
        json={
            "agent_execution_id": proposer.get_json()["execution"][
                "execution_id"
            ],
            "risk_level": "L4",
            "change_diff": {"reason": "HTTP identity-chain test"},
            "evidence_refs": ["test:http-proposal"],
            "token_estimate": 250,
        },
    )
    assert proposal.status_code == 201
    review = client.post(
        "/api/research-graph-proposals/"
        f"{proposal.get_json()['proposal']['proposal_id']}/reviews",
        json={
            "agent_execution_id": reviewer.get_json()["execution"][
                "execution_id"
            ],
            "disposition": "approved",
            "scope_drift": False,
            "semantic_uncertainty": False,
            "evidence_refs": ["test:http-review"],
        },
    )
    assert review.status_code == 201

    validated = client.post(
        "/api/research-graphs/factor-research/versions/2/validation",
        json=_server_validation_evidence(),
    )
    assert validated.status_code == 201

    audited = client.post(
        "/api/research-graphs/factor-research/versions/2/audit",
        json={
            "disposition": "approved",
            "grill_evidence": [{
                "question": "Does product support alter topology?",
                "answer": "No",
                "status": "pass",
            }],
        },
    )
    assert audited.status_code == 201

    graph = created.get_json()["graph"]
    proposal_row = proposal.get_json()["proposal"]
    nonce = uuid.uuid4().hex
    expires_at = time.time() + 300
    diff_hash = hashlib.sha256(orjson.dumps(
        {"reason": "HTTP identity-chain test"},
        option=orjson.OPT_SORT_KEYS,
    )).hexdigest()
    human_payload = {
        "owner_user_id": "alice",
        "graph_id": "factor-research",
        "graph_version": 2,
        "graph_hash": graph["content_hash"],
        "proposal_id": proposal_row["proposal_id"],
        "diff_hash": diff_hash,
        "nonce_hash": hashlib.sha256(nonce.encode()).hexdigest(),
        "authorized_by": "human-auditor",
        "expires_at": expires_at,
    }
    human_attestation = hmac.new(
        b"test-human-activation-secret",
        orjson.dumps(human_payload, option=orjson.OPT_SORT_KEYS),
        hashlib.sha256,
    ).hexdigest()
    authorization = client.post(
        "/api/research-human-activation-authorizations",
        json={
            **{
                key: value for key, value in human_payload.items()
                if key not in {"owner_user_id", "nonce_hash"}
            },
            "nonce": nonce,
            "human_attestation": human_attestation,
        },
    )
    assert authorization.status_code == 201
    activated = client.post(
        "/api/research-graphs/factor-research/versions/2/activate",
        json={
            "human_authorization_id": authorization.get_json()[
                "authorization"
            ]["authorization_id"],
        },
    )
    assert activated.status_code == 201
    assert activated.get_json()["graph"]["lifecycle"] == "active"

    receipt = _issue_receipt(
        node_id="hypothesis",
        product_group="equities",
        capability_ids=["research-hypothesis.preregister"],
    )
    instance = research_graphs.create_graph_instance(
        graph_id="factor-research",
        owner="alice",
        product_group="equities",
        workspace_id="http-workspace",
        token_budget=100,
        capability_receipt=receipt,
    )
    branch_id = instance["branches"][0]["branch_id"]
    context_response = client.get(
        f"/api/research-graph-instances/{instance['instance_id']}"
        f"/branches/{branch_id}/context"
    )
    next_response = client.get(
        f"/api/research-graph-instances/{instance['instance_id']}"
        f"/branches/{branch_id}/next"
    )
    assert context_response.status_code == 200
    assert next_response.status_code == 200
    assert "required_capabilities" in context_response.get_json()["context"]
    assert "candidate_edges" not in context_response.get_json()["context"]
    assert "candidate_edges" in next_response.get_json()["next"]
    assert "required_capabilities" not in next_response.get_json()["next"]

    history = client.get("/api/research-graphs/factor-research/versions")
    assert [item["lifecycle"] for item in history.get_json()["versions"]] == [
        "draft",
        "active",
    ]


def test_one_graph_branch_can_pause_without_stopping_another(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    graph = _draft_graph()
    graph["nodes"].extend([
        {
            "node_id": "capability_resolution",
            "kind": "capability",
            "purpose": "resolve capabilities",
            "enforcement": "audited",
            "required_capabilities": [],
            "entry_evidence": [],
            "exit_evidence": [],
        },
        {
            "node_id": "capability_gap",
            "kind": "capability_gap",
            "purpose": "classify a gap",
            "enforcement": "audited",
            "required_capabilities": ["capability-gap.classify"],
            "entry_evidence": [],
            "exit_evidence": [],
        },
    ])
    graph["entry_node"] = "hypothesis"
    graph["capability_descriptors"]["capability-gap.classify"] = _descriptor(
        "capability-gap.classify"
    )
    graph["edges"] = [
        {
            "edge_id": "hypothesis__resolution",
            "from_node": "hypothesis",
            "to_node": "capability_resolution",
            "edge_type": "conditional",
            "guard": {"hypothesis_frozen": True},
            "required_evidence": [],
            "counterexamples": [],
            "risk_level": "L1",
        },
        {
            "edge_id": "resolution__gap",
            "from_node": "capability_resolution",
            "to_node": "capability_gap",
            "edge_type": "failure",
            "guard": {"mandatory_binding_missing": True},
            "required_evidence": ["missing capability id"],
            "counterexamples": [],
            "risk_level": "L2",
        },
    ]
    graph["content_hash"] = _hash(graph)
    research_graphs.register_graph(graph, actor="curator")
    _approve_proposal()
    research_graphs.record_validation(
        graph_id="factor-research",
        version=2,
        actor="reviewer",
        evidence=_server_validation_evidence(),
    )
    research_graphs.record_audit(
        graph_id="factor-research",
        version=2,
        actor="auditor",
        disposition="approved",
        grill_evidence=[{"question": "isolated?", "answer": "yes"}],
    )
    _activate()
    instance = research_graphs.create_graph_instance(
        graph_id="factor-research",
        owner="alice",
        product_group="china_futures",
        workspace_id="workspace-1",
        token_budget=1000,
        capability_receipt=_issue_receipt(
            node_id="hypothesis",
            product_group="china_futures",
            capability_ids=["research-hypothesis.preregister"],
        ),
    )
    first = instance["branches"][0]
    second = research_graphs.fork_graph_branch(
        instance_id=instance["instance_id"],
        source_branch_id=first["branch_id"],
        owner="alice",
        label="independent hypothesis",
    )
    next_packet = research_graphs.build_graph_branch_next(
        instance_id=instance["instance_id"],
        branch_id=first["branch_id"],
        owner="alice",
    )
    assert next_packet["candidate_edges"] == [{
        "edge_id": "hypothesis__resolution",
        "to_node": "capability_resolution",
        "edge_type": "conditional",
        "risk_level": "L1",
        "readiness": "requires_evidence",
        "required_guard_fields": ["hypothesis_frozen"],
        "required_evidence": [],
        "blockers": [],
        "review_requirement": "none",
    }]
    assert next_packet["recommended_edge_ids"] == []
    assert next_packet["requires_agent_judgment"] is False
    assert next_packet["next_bytes"] == len(orjson.dumps(next_packet))
    assert next_packet["next_bytes"] <= 6000
    assert "required_capabilities" not in next_packet

    transition_statements: list[str] = []
    original_connect = research_graphs.connect_sqlite

    def traced_transition_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(transition_statements.append)
        return connection

    monkeypatch.setattr(
        research_graphs,
        "connect_sqlite",
        traced_transition_connect,
    )
    research_graphs.advance_graph_branch(
        instance_id=instance["instance_id"],
        branch_id=first["branch_id"],
        owner="alice",
        edge_id="hypothesis__resolution",
        evidence={"hypothesis_frozen": True},
    )
    monkeypatch.setattr(
        research_graphs,
        "connect_sqlite",
        original_connect,
    )
    transition_selects = [
        statement for statement in transition_statements
        if statement.lstrip().upper().startswith("SELECT ")
    ]
    assert len(transition_selects) == 2
    assert not any(
        "RESEARCH_GRAPH_VERSIONS" in statement.upper()
        for statement in transition_selects
    )
    assert sum(
        statement.lstrip().upper().startswith(
            "UPDATE RESEARCH_GRAPH_BRANCHES"
        )
        for statement in transition_statements
    ) == 1
    assert sum(
        statement.lstrip().upper().startswith(
            "INSERT INTO RESEARCH_GRAPH_TRACE"
        )
        for statement in transition_statements
    ) == 1
    paused = research_graphs.advance_graph_branch(
        instance_id=instance["instance_id"],
        branch_id=first["branch_id"],
        owner="alice",
        edge_id="resolution__gap",
        evidence={
            "mandatory_binding_missing": True,
            "evidence_refs": [
                f"artifact:capability-gap:{index}"
                for index in range(10)
            ],
            "token_telemetry": {
                "agent_role": "primary",
                "input_tokens": 120,
                "output_tokens": 30,
                "cache_read_tokens": 80,
                "skill_document_tokens": 0,
                "artifact_summary_tokens": 20,
                "reviewer_tokens": 40,
                "loaded_skill_ids": [],
            },
            "token_reservation_ids": [_commit_usage(
                instance_id=instance["instance_id"],
                input_tokens=160,
                output_tokens=30,
            )],
        },
    )
    untouched = research_graphs.load_graph_branch(
        instance_id=instance["instance_id"],
        branch_id=second["branch_id"],
        owner="alice",
    )

    assert paused["status"] == "paused"
    assert paused["current_node"] == "capability_gap"
    assert untouched["status"] == "running"
    assert untouched["current_node"] == "hypothesis"

    statements: list[str] = []
    original_connect = research_graphs.connect_sqlite

    def traced_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(research_graphs, "connect_sqlite", traced_connect)
    context = research_graphs.build_graph_branch_context(
        instance_id=instance["instance_id"],
        branch_id=first["branch_id"],
        owner="alice",
    )
    assert set(context) == {
        "graph",
        "branch",
        "node",
            "required_capabilities",
            "triggered_capabilities",
            "undetermined_conditions",
            "evidence_refs",
            "omitted_evidence_count",
            "history_cursor",
        "open_gaps",
        "skill_policy",
        "token_telemetry",
            "review_policy",
            "review_gate",
            "context_bytes",
    }
    assert context["graph"] == "factor-research@v3"
    assert "nodes" not in context
    assert context["token_telemetry"]["primary_total_tokens"] == 150
    assert context["token_telemetry"]["team_total_tokens"] == 190
    assert context["token_telemetry"]["total_tokens"] == 190
    assert context["review_policy"]["L1"] == "deterministic_only"
    assert context["evidence_refs"] == [
        f"artifact:capability-gap:{index}"
        for index in range(2, 10)
    ]
    assert context["omitted_evidence_count"] == 2
    assert context["history_cursor"].startswith("trace:")
    assert not any(
        "FROM RESEARCH_GRAPH_TRACE" in statement.upper()
        for statement in statements
    )
    selects = [
        statement for statement in statements
        if statement.lstrip().upper().startswith("SELECT ")
    ]
    assert len(selects) == 3
    assert not any(
        "RESEARCH_GRAPH_VERSIONS" in statement.upper()
        for statement in selects
    )

    monkeypatch.setattr(
        research_graphs,
        "connect_sqlite",
        original_connect,
    )
    with original_connect(Settings.CACHE_DB_PATH) as connection:
        connection.execute(
            """
            UPDATE research_graph_branches SET
                cumulative_input_tokens=0,
                cumulative_output_tokens=0,
                cumulative_cache_read_tokens=0,
                cumulative_skill_document_tokens=0,
                cumulative_artifact_summary_tokens=0,
                cumulative_reviewer_tokens=0,
                skill_document_load_count=0,
                skill_context_cache_hits=0,
                evidence_refs_json='[]',
                omitted_evidence_count=0,
                latest_trace_id='',
                trace_count=0,
                aggregate_version=0
            WHERE branch_id=?
            """,
            (first["branch_id"],),
        )
    research_graphs.ensure_schema()
    migrated_context = research_graphs.build_graph_branch_context(
        instance_id=instance["instance_id"],
        branch_id=first["branch_id"],
        owner="alice",
    )
    assert migrated_context["token_telemetry"]["team_total_tokens"] == 190
    assert migrated_context["evidence_refs"] == context["evidence_refs"]
    assert migrated_context["omitted_evidence_count"] == 2


def test_transition_stores_only_target_node_resolution(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    graph = _draft_graph()
    graph["nodes"].append({
        "node_id": "validation",
        "kind": "research",
        "purpose": "validate factor",
        "enforcement": "audited",
        "required_capabilities": ["factor-validation.cross-sectional-ic"],
        "entry_evidence": [],
        "exit_evidence": [],
    })
    graph["entry_node"] = "hypothesis"
    graph["capability_descriptors"][
        "factor-validation.cross-sectional-ic"
    ] = _descriptor("factor-validation.cross-sectional-ic")
    graph["edges"] = [{
        "edge_id": "hypothesis__validation",
        "from_node": "hypothesis",
        "to_node": "validation",
        "edge_type": "conditional",
        "guard": {"hypothesis_frozen": True},
        "required_evidence": [],
        "counterexamples": [],
        "risk_level": "L1",
    }]
    graph["content_hash"] = _hash(graph)
    research_graphs.register_graph(graph, actor="curator")
    _approve_proposal()
    research_graphs.record_validation(
        graph_id="factor-research",
        version=2,
        actor="reviewer",
        evidence=_server_validation_evidence(),
    )
    research_graphs.record_audit(
        graph_id="factor-research",
        version=2,
        actor="auditor",
        disposition="approved",
        grill_evidence=[{"question": "local?", "answer": "yes"}],
    )
    _activate()
    instance = research_graphs.create_graph_instance(
        graph_id="factor-research",
        owner="alice",
        product_group="equities",
        workspace_id="workspace-2",
        token_budget=12,
        capability_receipt=_issue_receipt(
            node_id="hypothesis",
            product_group="equities",
            capability_ids=["research-hypothesis.preregister"],
        ),
    )
    branch = instance["branches"][0]
    target_receipt = _issue_receipt(
        node_id="validation",
        product_group="equities",
        capability_ids=["factor-validation.cross-sectional-ic"],
    )

    research_graphs.advance_graph_branch(
        instance_id=instance["instance_id"],
        branch_id=branch["branch_id"],
        owner="alice",
        edge_id="hypothesis__validation",
        evidence={
            "hypothesis_frozen": True,
            "target_capability_receipt": target_receipt,
            "token_telemetry": {
                "input_tokens": 10,
                "output_tokens": 2,
                "cache_read_tokens": 8,
                "skill_document_tokens": 5,
                "artifact_summary_tokens": 0,
                "reviewer_tokens": 0,
                "skill_document_load_count": 1,
                "skill_context_cache_hits": 0,
            },
            "token_reservation_ids": [_commit_usage(
                instance_id=instance["instance_id"],
                input_tokens=10,
                output_tokens=2,
            )],
        },
    )
    context = research_graphs.build_graph_branch_context(
        instance_id=instance["instance_id"],
        branch_id=branch["branch_id"],
        owner="alice",
    )

    assert context["node"]["node_id"] == "validation"
    assert context["required_capabilities"][0]["binding"] == {
        "capability_id": "factor-validation.cross-sectional-ic",
        **research_graphs.load_active_graph(
            graph_id="factor-research"
        )["capability_descriptors"][
            "factor-validation.cross-sectional-ic"
        ],
    }
    assert "target_capability_resolution" not in json.dumps(
        context, sort_keys=True,
    )
    assert len(json.dumps(context)) < 6000
    assert context["token_telemetry"]["skill_document_load_count"] == 1
    assert context["token_telemetry"]["budget"] == {
        "limit": 12,
        "used": 12,
        "reserved": 0,
        "remaining": 0,
        "exceeded": True,
        "authority": "trusted_provider_usage_receipts",
    }
    assert context["branch"]["status"] == "running"
    assert context["review_gate"]["max_new_reviewers"] == 0
    assert context["review_gate"]["running_backend_jobs_action"] == "continue"
    assert context["skill_policy"]["agent_action"] == (
        "reuse_matching_runtime_skill_else_load_after_trigger_and_approval"
    )
    with research_graphs.connect_sqlite(Settings.CACHE_DB_PATH) as connection:
        before = connection.execute(
            """
            SELECT created_at
            FROM research_graph_node_resolutions
            WHERE instance_id=? AND branch_id=? AND node_id=?
            """,
            (
                instance["instance_id"],
                branch["branch_id"],
                "validation",
            ),
        ).fetchone()
        resolution = research_graphs._load_node_resolution(
            connection,
            instance_id=instance["instance_id"],
            branch_id=branch["branch_id"],
            node_id="validation",
        )
        research_graphs._store_node_resolution(
            connection,
            instance_id=instance["instance_id"],
            branch_id=branch["branch_id"],
            node_id="validation",
            resolution=resolution,
        )
        unchanged_write_count = int(
            connection.execute("SELECT changes()").fetchone()[0]
        )
        after = connection.execute(
            """
            SELECT created_at
            FROM research_graph_node_resolutions
            WHERE instance_id=? AND branch_id=? AND node_id=?
            """,
            (
                instance["instance_id"],
                branch["branch_id"],
                "validation",
            ),
        ).fetchone()
    assert unchanged_write_count == 0
    assert after["created_at"] == before["created_at"]
    assert b"factortester.analysis.ic" not in (
        tmp_path / "graphs.sqlite"
    ).read_bytes()


def test_token_budget_reservation_denies_before_launch_and_fails_closed(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    research_graphs.create_token_budget(
        owner_user_id="alice",
        scope_id="hard-limit",
        token_limit=100,
    )
    granted = research_graphs.reserve_tokens(
        owner_user_id="alice",
        scope_id="hard-limit",
        work_kind="reviewer",
        max_input_tokens=60,
        max_output_tokens=20,
    )

    with pytest.raises(ValueError, match="reservation denied"):
        research_graphs.reserve_tokens(
            owner_user_id="alice",
            scope_id="hard-limit",
            work_kind="reviewer",
            max_input_tokens=20,
            max_output_tokens=10,
        )
    with pytest.raises(ValueError, match="reservation is required"):
        _create_attested_agent("reviewer", "")
    with pytest.raises(ValueError, match="not configured"):
        monkeypatch.delenv("RESEARCH_PROVIDER_USAGE_SECRET", raising=False)
        research_graphs.ingest_provider_usage_receipt(
            reservation_id=granted["reservation_id"],
            provider="untrusted",
            provider_request_id="request-1",
            input_tokens=10,
            output_tokens=5,
            usage_attestation="forged",
        )

    released = research_graphs.release_token_reservation(
        owner_user_id="alice",
        reservation_id=granted["reservation_id"],
    )
    budget = research_graphs.load_token_budget(
        owner_user_id="alice",
        scope_id="hard-limit",
    )
    assert released["released_tokens"] == 80
    assert budget["available_tokens"] == 100


def test_context_exposes_only_triggered_and_undetermined_conditions(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    graph = _draft_graph()
    node = graph["nodes"][0]
    node["conditional_capabilities"] = [
        {
            "capability_id": "market-microstructure.intraday-diagnose",
            "predicate": {"field": "signal.frequency", "in": ["MIN1"]},
            "explanation": "Use only for intraday signals.",
        },
        {
            "capability_id": "factor-combination.multi-factor",
            "predicate": {"field": "factor.is_multi", "equals": True},
            "explanation": "Use only for multi-factor research.",
        },
    ]
    for capability_id in (
        "market-microstructure.intraday-diagnose",
        "factor-combination.multi-factor",
    ):
        graph["capability_descriptors"][capability_id] = _descriptor(
            capability_id
        )
    graph["content_hash"] = _hash(graph)
    research_graphs.register_graph(graph, actor="curator")
    _approve_proposal()
    research_graphs.record_validation(
        graph_id="factor-research",
        version=2,
        actor="reviewer",
        evidence=_server_validation_evidence(),
    )
    research_graphs.record_audit(
        graph_id="factor-research",
        version=2,
        actor="auditor",
        disposition="approved",
        grill_evidence=[{"question": "conditional?", "answer": "bounded"}],
    )
    active = _activate()
    instance = research_graphs.create_graph_instance(
        graph_id="factor-research",
        owner="alice",
        product_group="equities",
        workspace_id="workspace-conditional",
        token_budget=1000,
        capability_receipt=_issue_receipt(
            node_id="hypothesis",
            product_group="equities",
            capability_ids=[
                "research-hypothesis.preregister",
                "market-microstructure.intraday-diagnose",
            ],
            triggered_capability_ids=[
                "market-microstructure.intraday-diagnose",
            ],
            undetermined_conditions=[{
                "capability_id": "factor-combination.multi-factor",
                "explanation": "factor.is_multi is unavailable",
            }],
        ),
    )
    context = research_graphs.build_graph_branch_context(
        instance_id=instance["instance_id"],
        branch_id=instance["branches"][0]["branch_id"],
        owner="alice",
    )

    assert "conditional_capabilities" not in context
    assert [
        item["capability_id"]
        for item in context["triggered_capabilities"]
    ] == ["market-microstructure.intraday-diagnose"]
    assert context["undetermined_conditions"] == [{
        "capability_id": "factor-combination.multi-factor",
        "explanation": "factor.is_multi is unavailable",
    }]
    assert context["context_bytes"] == len(orjson.dumps(context))
    assert context["context_bytes"] <= 6000
    assert active["version"] == 3
