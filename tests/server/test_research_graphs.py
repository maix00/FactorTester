from __future__ import annotations

from copy import deepcopy
import hashlib
import hmac
import json
import os
import uuid

from flask import Flask
import orjson
import pytest

import settings as Settings
from server.modules.single_factor_test import sft_bp
from server.services import research_graphs


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


def _token_metrics() -> dict:
    return {
        "routine_context_bytes": 2400,
        "full_graph_loaded_for_routine": False,
        "untriggered_conditionals_in_context": 0,
        "future_node_gaps_blocked": 0,
        "routine_subagent_count": 0,
        "shadow_graph_total_tokens": 800,
        "shadow_baseline_total_tokens": 1000,
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


def _agent_execution(role: str) -> dict:
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
    return research_graphs.create_agent_execution(
        owner_user_id="alice",
        actor_role=role,
        model_id="test-model",
        reservation_id=reservation["reservation_id"],
    )


def _issue_receipt(
    *,
    node_id: str,
    product_group: str,
    capability_ids: list[str],
    triggered_capability_ids: list[str] | None = None,
    undetermined_conditions: list[dict] | None = None,
) -> dict:
    active = research_graphs.load_active_graph(
        graph_id="factor-research"
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
    )


def _commit_usage(
    *,
    instance_id: str,
    input_tokens: int,
    output_tokens: int,
) -> str:
    secret = "test-provider-secret"
    os.environ["RESEARCH_PROVIDER_USAGE_SECRET"] = secret
    reservation = research_graphs.reserve_tokens(
        owner_user_id="alice",
        scope_id=f"instance:{instance_id}",
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
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "graphs.sqlite")
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
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "graphs.sqlite")
    draft = research_graphs.register_graph(_draft_graph(), actor="curator-agent")

    changed = _draft_graph()
    changed["nodes"][0]["purpose"] = "changed"
    changed["content_hash"] = _hash(changed)
    with pytest.raises(research_graphs.GraphVersionConflict):
        research_graphs.register_graph(changed, actor="curator-agent")

    _approve_proposal()
    research_graphs.record_validation(
        graph_id="factor-research",
        version=2,
        actor="review-agent",
        evidence={
            "replay_passed": True,
            "shadow_passed": True,
            "capability_resolution_complete": True,
            "unaffected_jobs_preserved": True,
            "token_efficiency_passed": True,
            "token_metrics": _token_metrics(),
        },
    )
    research_graphs.record_audit(
        graph_id="factor-research",
        version=2,
        actor="human-auditor",
        disposition="approved",
        grill_evidence=[
            {"question": "Can holdout select?", "answer": "No", "status": "pass"}
        ],
    )
    active = research_graphs.activate_graph(
        graph_id="factor-research",
        source_version=2,
        actor="curator-agent",
    )

    assert draft["lifecycle"] == "draft"
    assert active["version"] == 3
    assert active["lifecycle"] == "active"
    assert active["parent_version"] == 2
    assert research_graphs.load_active_graph(
        graph_id="factor-research"
    )["content_hash"] == active["content_hash"]


def test_activation_requires_replay_shadow_capability_and_job_isolation(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "graphs.sqlite")
    research_graphs.register_graph(_draft_graph(), actor="curator-agent")
    _approve_proposal()
    research_graphs.record_validation(
        graph_id="factor-research",
        version=2,
        actor="review-agent",
        evidence={
            "replay_passed": True,
            "shadow_passed": False,
            "capability_resolution_complete": True,
            "unaffected_jobs_preserved": True,
            "token_efficiency_passed": True,
            "token_metrics": _token_metrics(),
        },
    )
    research_graphs.record_audit(
        graph_id="factor-research",
        version=2,
        actor="human-auditor",
        disposition="approved",
        grill_evidence=[{"question": "Shadow?", "answer": "Pending"}],
    )

    with pytest.raises(research_graphs.GraphActivationBlocked, match="shadow_passed"):
        research_graphs.activate_graph(
            graph_id="factor-research",
            source_version=2,
            actor="curator-agent",
        )


def test_validation_rejects_a_token_efficient_claim_with_regression(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "graphs.sqlite")
    research_graphs.register_graph(_draft_graph(), actor="curator-agent")
    regressed = _token_metrics()
    regressed["routine_context_bytes"] = 7000
    regressed["routine_subagent_count"] = 1

    with pytest.raises(ValueError, match="token efficiency checks failed"):
        research_graphs.record_validation(
            graph_id="factor-research",
            version=2,
            actor="review-agent",
            evidence={
                "replay_passed": True,
                "shadow_passed": True,
                "capability_resolution_complete": True,
                "unaffected_jobs_preserved": True,
                "token_efficiency_passed": True,
                "token_metrics": regressed,
            },
        )


def test_review_disagreement_adds_a_third_reviewer_only_then(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "graphs.sqlite")
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
        evidence={
            "replay_passed": True,
            "shadow_passed": True,
            "capability_resolution_complete": True,
            "unaffected_jobs_preserved": True,
            "token_efficiency_passed": True,
            "token_metrics": _token_metrics(),
        },
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
        research_graphs.activate_graph(
            graph_id="factor-research",
            source_version=2,
            actor="curator-agent",
        )

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
    active = research_graphs.activate_graph(
        graph_id="factor-research",
        source_version=2,
        actor="curator-agent",
    )
    assert active["lifecycle"] == "active"


def test_audited_rollback_moves_only_the_active_pointer(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "graphs.sqlite")
    research_graphs.register_graph(_draft_graph(), actor="curator-agent")
    _approve_proposal()
    research_graphs.record_validation(
        graph_id="factor-research",
        version=2,
        actor="validation-agent",
        evidence={
            "replay_passed": True,
            "shadow_passed": True,
            "capability_resolution_complete": True,
            "unaffected_jobs_preserved": True,
            "token_efficiency_passed": True,
            "token_metrics": _token_metrics(),
        },
    )
    research_graphs.record_audit(
        graph_id="factor-research",
        version=2,
        actor="human-auditor",
        disposition="approved",
        grill_evidence=[{"question": "activate?", "answer": "yes"}],
    )
    first_active = research_graphs.activate_graph(
        graph_id="factor-research",
        source_version=2,
        actor="curator-agent",
    )
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
        evidence={
            "replay_passed": True,
            "shadow_passed": True,
            "capability_resolution_complete": True,
            "unaffected_jobs_preserved": True,
            "token_efficiency_passed": True,
            "token_metrics": _token_metrics(),
        },
    )
    research_graphs.record_audit(
        graph_id="factor-research",
        version=4,
        actor="human-auditor",
        disposition="approved",
        grill_evidence=[{"question": "activate refined?", "answer": "yes"}],
    )
    second_active = research_graphs.activate_graph(
        graph_id="factor-research",
        source_version=4,
        actor="curator-agent",
    )

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
    proposer = client.post("/api/research-agent-executions", json={
        "actor_role": "proposer",
        "model_id": "test-proposer",
        "reservation_id": proposer_reservation["reservation_id"],
    })
    reviewer = client.post("/api/research-agent-executions", json={
        "actor_role": "reviewer",
        "model_id": "test-reviewer",
        "reservation_id": reviewer_reservation["reservation_id"],
    })
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
        json={
            "replay_passed": True,
            "shadow_passed": True,
            "capability_resolution_complete": True,
            "unaffected_jobs_preserved": True,
            "token_efficiency_passed": True,
            "token_metrics": _token_metrics(),
        },
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

    activated = client.post(
        "/api/research-graphs/factor-research/versions/2/activate",
        json={},
    )
    assert activated.status_code == 201
    assert activated.get_json()["graph"]["lifecycle"] == "active"

    history = client.get("/api/research-graphs/factor-research/versions")
    assert [item["lifecycle"] for item in history.get_json()["versions"]] == [
        "draft",
        "active",
    ]


def test_one_graph_branch_can_pause_without_stopping_another(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "graphs.sqlite")
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
        evidence=({gate: True for gate in (
            "replay_passed",
            "shadow_passed",
            "capability_resolution_complete",
            "unaffected_jobs_preserved",
            "token_efficiency_passed",
        )} | {"token_metrics": _token_metrics()}),
    )
    research_graphs.record_audit(
        graph_id="factor-research",
        version=2,
        actor="auditor",
        disposition="approved",
        grill_evidence=[{"question": "isolated?", "answer": "yes"}],
    )
    research_graphs.activate_graph(
        graph_id="factor-research", source_version=2, actor="curator",
    )
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

    research_graphs.advance_graph_branch(
        instance_id=instance["instance_id"],
        branch_id=first["branch_id"],
        owner="alice",
        edge_id="hypothesis__resolution",
        evidence={"hypothesis_frozen": True},
    )
    paused = research_graphs.advance_graph_branch(
        instance_id=instance["instance_id"],
        branch_id=first["branch_id"],
        owner="alice",
        edge_id="resolution__gap",
        evidence={
            "mandatory_binding_missing": True,
            "evidence_refs": ["capability://missing/bootstrap-sharpe"],
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

    context = research_graphs.build_graph_branch_context(
        instance_id=instance["instance_id"],
        branch_id=first["branch_id"],
        owner="alice",
    )
    assert set(context) == {
        "graph",
        "branch",
        "node",
            "available_edges",
            "required_capabilities",
            "triggered_capabilities",
            "undetermined_conditions",
            "evidence_refs",
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


def test_transition_stores_only_target_node_resolution(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "graphs.sqlite")
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
        evidence=({gate: True for gate in (
            "replay_passed",
            "shadow_passed",
            "capability_resolution_complete",
            "unaffected_jobs_preserved",
            "token_efficiency_passed",
        )} | {"token_metrics": _token_metrics()}),
    )
    research_graphs.record_audit(
        graph_id="factor-research",
        version=2,
        actor="auditor",
        disposition="approved",
        grill_evidence=[{"question": "local?", "answer": "yes"}],
    )
    research_graphs.activate_graph(
        graph_id="factor-research", source_version=2, actor="curator",
    )
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
    assert b"factortester.analysis.ic" not in (
        tmp_path / "graphs.sqlite"
    ).read_bytes()


def test_token_budget_reservation_denies_before_launch_and_fails_closed(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "graphs.sqlite")
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
        research_graphs.create_agent_execution(
            owner_user_id="alice",
            actor_role="reviewer",
        )
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
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "graphs.sqlite")
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
        evidence={
            "replay_passed": True,
            "shadow_passed": True,
            "capability_resolution_complete": True,
            "unaffected_jobs_preserved": True,
            "token_efficiency_passed": True,
            "token_metrics": _token_metrics(),
        },
    )
    research_graphs.record_audit(
        graph_id="factor-research",
        version=2,
        actor="auditor",
        disposition="approved",
        grill_evidence=[{"question": "conditional?", "answer": "bounded"}],
    )
    active = research_graphs.activate_graph(
        graph_id="factor-research",
        source_version=2,
        actor="curator",
    )
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
