from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import uuid

from flask import Flask
import orjson
import pytest

import settings as Settings
from server.jobs.models import JobRecord
from server.jobs.repository import JobRepository
from server.jobs.states import JobStatus
from server.modules.single_factor_test import sft_bp
from server.services import research_graphs, research_runs
from server.services import agent_flow


def _initialize_graph_db(tmp_path, monkeypatch) -> None:
    """Run graph migrations explicitly before exercising request hot paths."""
    monkeypatch.setattr(
        Settings,
        "CACHE_DB_PATH",
        tmp_path / "graphs.sqlite",
    )
    research_graphs.ensure_schema()
    monkeypatch.setenv(
        "RESEARCH_HUMAN_ACTIVATION_SECRET",
        "test-human-activation-secret",
    )
    agent_flow.clear_store_cache()


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
        conversation_ref="auth-conversation:test-graph-governance",
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


def _latest_proposal(
    *,
    graph_version: int = 2,
    owner_user_id: str = "alice",
) -> dict:
    graph = research_graphs.load_graph(
        graph_id="factor-research",
        version=graph_version,
    )
    prefix = (
        f"graph-proposal:factor-research@{graph_version}:"
        f"{graph['content_hash']}:"
    )
    with research_graphs.connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT * FROM research_maintenance_cases
            WHERE owner_user_id=? AND kind='approval_gate'
            ORDER BY created_at DESC, case_id DESC
            """,
            (owner_user_id,),
        ).fetchall()
    for row in rows:
        affected_refs = orjson.loads(row["affected_refs_json"])
        proposal_refs = [
            ref for ref in affected_refs if ref.startswith(prefix)
        ]
        if len(proposal_refs) == 1:
            return {
                "proposal_id": row["case_id"],
                "diff_hash": proposal_refs[0][len(prefix):],
                "conversation_ref": row["conversation_ref"],
                "status": row["status"],
            }
    raise AssertionError("activation Gate not found")


def _create_agent_invocation(
    role: str,
    *,
    principal_label: str | None = None,
    lineage_label: str | None = None,
    model_id: str = "test-model",
    agent_id: str | None = None,
    sponsor_agent_id: str = "",
    settle: bool = True,
) -> dict:
    authority_scope = (
        "server_backend_code"
        if role in {"implementation_agent", "backend_verifier"}
        else "local_research"
    )
    principal_hash = hashlib.sha256(
        (principal_label or uuid.uuid4().hex).encode()
    ).hexdigest()
    lineage_hash = hashlib.sha256(
        (lineage_label or uuid.uuid4().hex).encode()
    ).hexdigest()
    store = agent_flow.get_store()
    invocation = store.reserve_invocation(
        owner_user_id="alice",
        agent_id=agent_id or f"test:{role}:{uuid.uuid4().hex}",
        sponsor_agent_id=sponsor_agent_id,
        actor_role=role,
        authority_scope=authority_scope,
        purpose=role,
        runtime_id="test-runtime",
        model_id=model_id,
        max_input_tokens=400,
        max_output_tokens=200,
        agent_principal_hash=principal_hash,
        lineage_hash=lineage_hash,
    )
    if settle:
        store.settle_invocation(
            owner_user_id="alice",
            invocation_id=invocation["invocation_id"],
            input_tokens=10,
            output_tokens=5,
            provider_request_id=uuid.uuid4().hex,
        )
    loaded = store.load_invocation(
        owner_user_id="alice",
        invocation_id=invocation["invocation_id"],
    )
    return loaded | {"execution_id": loaded["invocation_id"]}


def _agent_execution(
    role: str,
    *,
    principal_label: str | None = None,
    lineage_label: str | None = None,
) -> dict:
    return _create_agent_invocation(
        role,
        principal_label=principal_label,
        lineage_label=lineage_label,
    )


def _agent_http_payload(
    role: str,
    *,
    model_id: str,
) -> dict:
    authority_scope = (
        "server_backend_code"
        if role in {"implementation_agent", "backend_verifier"}
        else "local_research"
    )
    principal_hash = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    lineage_hash = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    return {
        "agent_id": f"http:{role}:{uuid.uuid4().hex}",
        "actor_role": role,
        "authority_scope": authority_scope,
        "purpose": role,
        "runtime_id": "test-runtime",
        "model_id": model_id,
        "max_input_tokens": 400,
        "max_output_tokens": 200,
        "agent_principal_hash": principal_hash,
        "lineage_hash": lineage_hash,
    }


def _human_authorization(
    *,
    graph_version: int = 2,
    owner_user_id: str = "alice",
) -> dict:
    graph = research_graphs.load_graph(
        graph_id="factor-research",
        version=graph_version,
    )
    proposal = _latest_proposal(
        graph_version=graph_version,
        owner_user_id=owner_user_id,
    )
    return research_graphs.authorize_graph_activation(
        owner_user_id=owner_user_id,
        graph_id="factor-research",
        graph_version=graph_version,
        proposal_id=proposal["proposal_id"],
        graph_hash=graph["content_hash"],
        diff_hash=proposal["diff_hash"],
        conversation_ref=proposal["conversation_ref"],
        approval_ref=f"auth-conversation-event:{uuid.uuid4().hex}",
    )


def _activate(graph_version: int = 2) -> dict:
    authorization = _human_authorization(graph_version=graph_version)
    return research_graphs.activate_graph(
        graph_id="factor-research",
        source_version=graph_version,
        actor="alice",
        human_authorization_id=authorization["authorization_id"],
    )


def _active_instance(*, workspace_id: str) -> dict:
    research_graphs.register_graph(_draft_graph(), actor="curator-agent")
    proposal, _ = _approve_proposal()
    research_graphs.record_validation(
        graph_id="factor-research",
        version=2,
        proposal_id=proposal["proposal_id"],
        actor="alice",
        evidence=_server_validation_evidence(),
    )
    research_graphs.record_audit(
        graph_id="factor-research",
        version=2,
        proposal_id=proposal["proposal_id"],
        actor="alice",
        disposition="approved",
        grill_evidence=[{"question": "activate?", "answer": "yes"}],
        grill_ref="grill-with-docs:test-active-instance",
    )
    _activate()
    receipt = _issue_receipt(
        node_id="hypothesis",
        product_group="equities",
        capability_ids=["research-hypothesis.preregister"],
    )
    return research_graphs.create_graph_instance(
        graph_id="factor-research",
        owner="alice",
        product_group="equities",
        workspace_id=workspace_id,
        token_budget=1000,
        capability_receipt=receipt,
    )


def _succeeded_job(
    *,
    workspace_id: str,
    worker_exitcode: int = 0,
) -> dict:
    run_spec = {
        "workspace_id": workspace_id,
        "factor": "test-factor",
    }
    run = research_runs.create_run(
        owner="alice",
        workspace_id=workspace_id,
        configuration_id=uuid.uuid4().hex,
        configuration_revision=1,
        run_spec=run_spec,
    )
    repository = JobRepository()
    job = repository.create(JobRecord(
        job_id=uuid.uuid4().hex,
        run_id=run["run_id"],
        owner="alice",
        workspace_id=workspace_id,
        kind="backtest",
        status=JobStatus.SUBMITTED,
        source_revision="test-backend-revision",
        runner_path="test:runner",
        job_spec={
            "run_id": run["run_id"],
            "workspace_id": workspace_id,
            "run_spec": run_spec,
        },
        run_spec_hash=run["run_spec_hash"],
    ))
    repository.transition(job.job_id, JobStatus.PLANNING)
    repository.set_execution_plan(
        job.job_id,
        plan={"runner": "test:runner", "steps": ["compute"]},
        notices=[],
        requires_confirmation=False,
    )
    repository.transition(job.job_id, JobStatus.RUNNING, worker_pid=123)
    job = repository.transition(
        job.job_id,
        JobStatus.SUCCEEDED,
        worker_exitcode=worker_exitcode,
        result_summary={"sharpe": 1.2, "observations": 1000},
    )
    return {"run": run, "job": job}


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
    bindings = []
    triggered_bindings = []
    triggered_ids = set(triggered_capability_ids or [])
    for capability_id in capability_ids:
        descriptor = active["capability_descriptors"][capability_id]
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
        approval_refs={},
        provider_conformance_hash="e" * 64,
        shadow_mode=shadow_mode,
    )


def _commit_scope_usage(
    *,
    scope_id: str,
    input_tokens: int,
    output_tokens: int,
) -> str:
    store = agent_flow.get_store()
    invocation = store.reserve_invocation(
        owner_user_id="alice",
        agent_id=scope_id,
        actor_role="researcher",
        authority_scope="local_research",
        purpose="research",
        runtime_id="test-runtime",
        model_id="test-model",
        max_input_tokens=input_tokens,
        max_output_tokens=output_tokens,
        agent_principal_hash=hashlib.sha256(scope_id.encode()).hexdigest(),
        lineage_hash=hashlib.sha256(
            f"{scope_id}:lineage".encode()
        ).hexdigest(),
    )
    store.settle_invocation(
        owner_user_id="alice",
        invocation_id=invocation["invocation_id"],
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        provider_request_id=uuid.uuid4().hex,
    )
    return invocation["invocation_id"]


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
    flow_store = agent_flow.get_store()
    flow_store.configure_token_limit(
        owner_user_id="alice",
        agent_id=f"instance:{instance['instance_id']}",
        token_limit=1000,
    )
    if graph_tokens:
        _commit_usage(
            instance_id=instance["instance_id"],
            input_tokens=max(graph_tokens - 10, 0),
            output_tokens=min(graph_tokens, 10),
        )
    if launch_subagent:
        _create_agent_invocation(
            "reviewer",
            agent_id=f"instance:{instance['instance_id']}",
            sponsor_agent_id="primary-research-agent",
        )
    baseline_scope_id = f"research-run:{baseline_run['run_id']}"
    flow_store.configure_token_limit(
        owner_user_id="alice",
        agent_id=baseline_scope_id,
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

    proposal, _ = _approve_proposal()
    validation = research_graphs.record_validation(
        graph_id="factor-research",
        version=2,
        proposal_id=proposal["proposal_id"],
        actor="alice",
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
        proposal_id=proposal["proposal_id"],
        actor="alice",
        disposition="approved",
        grill_evidence=[
            {"question": "Can holdout select?", "answer": "No", "status": "pass"}
        ],
        grill_ref="grill-with-docs:test-version-activation",
    )
    active = _activate()

    assert draft["lifecycle"] == "draft"
    assert active["version"] == 3
    assert active["lifecycle"] == "active"
    assert active["parent_version"] == 2
    assert research_graphs.load_active_graph(
        graph_id="factor-research"
    )["content_hash"] == active["content_hash"]


def test_agent_invocation_rejects_incomplete_identity_provenance(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="agent_principal_hash"):
        agent_flow.get_store().reserve_invocation(
            owner_user_id="alice",
            agent_id="test:invalid-identity",
            actor_role="proposer",
            authority_scope="local_research",
            purpose="proposal",
            runtime_id="test-runtime",
            model_id="test-model",
            max_input_tokens=400,
            max_output_tokens=200,
            agent_principal_hash="forged",
            lineage_hash="b" * 64,
        )


def test_local_research_agent_cannot_claim_backend_code_roles(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    for role in ("backend_verifier", "implementation_agent"):
        with pytest.raises(ValueError, match="server_backend_code"):
            agent_flow.get_store().reserve_invocation(
                owner_user_id="alice",
                agent_id=f"test:{role}",
                actor_role=role,
                authority_scope="local_research",
                purpose=role,
                runtime_id="test-runtime",
                model_id="test-model",
                max_input_tokens=10,
                max_output_tokens=5,
                agent_principal_hash="a" * 64,
                lineage_hash="b" * 64,
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
        conversation_ref="auth-conversation:test-independent-review",
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
    proposal, _ = _approve_proposal()
    research_graphs.record_validation(
        graph_id="factor-research",
        version=2,
        proposal_id=proposal["proposal_id"],
        actor="alice",
        evidence=_server_validation_evidence(),
    )
    research_graphs.record_audit(
        graph_id="factor-research",
        version=2,
        proposal_id=proposal["proposal_id"],
        actor="alice",
        disposition="approved",
        grill_evidence=[{"question": "activate?", "answer": "yes"}],
        grill_ref="grill-with-docs:test-one-time-approval",
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
        gate = conn.execute(
            """
            SELECT status, latest_result_ref
            FROM research_maintenance_cases
            WHERE case_id=?
            """,
            (authorization["authorization_id"],),
        ).fetchone()
    assert gate["status"] == "resolved"
    assert gate["latest_result_ref"].startswith("active-graph:")


def test_human_authorization_rejects_mismatched_conversation(
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

    with pytest.raises(ValueError, match="conversation does not match"):
        research_graphs.authorize_graph_activation(
            owner_user_id="alice",
            graph_id="factor-research",
            graph_version=2,
            proposal_id=proposal["proposal_id"],
            graph_hash=graph["content_hash"],
            diff_hash=diff_hash,
            conversation_ref="auth-conversation:other-session",
            approval_ref="auth-conversation-event:forged",
        )


def test_human_authorization_requires_conversation_event_reference(
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

    with pytest.raises(ValueError, match="authenticated conversation event"):
        research_graphs.authorize_graph_activation(
            owner_user_id="alice",
            graph_id="factor-research",
            graph_version=2,
            proposal_id=proposal["proposal_id"],
            graph_hash=graph["content_hash"],
            diff_hash=diff_hash,
            conversation_ref=proposal["conversation_ref"],
            approval_ref="manual-text:yes",
        )


def test_activation_gate_hot_path_is_one_transaction_with_bounded_sql(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    research_graphs.register_graph(_draft_graph(), actor="curator-agent")
    proposal, _ = _approve_proposal()
    research_graphs.record_validation(
        graph_id="factor-research",
        version=2,
        proposal_id=proposal["proposal_id"],
        actor="alice",
        evidence=_server_validation_evidence(),
    )
    research_graphs.record_audit(
        graph_id="factor-research",
        version=2,
        proposal_id=proposal["proposal_id"],
        actor="alice",
        disposition="approved",
        grill_evidence=[{"question": "activate?", "answer": "yes"}],
        grill_ref="grill-with-docs:test-bounded-activation-sql",
    )
    authorization = _human_authorization()
    statements: list[str] = []
    original_connect = research_graphs.connect_sqlite

    def traced_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(research_graphs, "connect_sqlite", traced_connect)
    active = research_graphs.activate_graph(
        graph_id="factor-research",
        source_version=2,
        actor="alice",
        human_authorization_id=authorization["authorization_id"],
    )

    normalized = [statement.lstrip().upper() for statement in statements]
    reads = [
        statement for statement in normalized
        if statement.startswith("SELECT ")
    ]
    writes = [
        statement for statement in normalized
        if statement.startswith(("INSERT ", "UPDATE ", "DELETE ", "REPLACE "))
    ]
    assert active["lifecycle"] == "active"
    assert len(reads) <= 3
    assert len(writes) == 3
    assert sum(
        statement.startswith("BEGIN IMMEDIATE")
        for statement in normalized
    ) == 1
    assert not any(
        legacy_name in statement
        for statement in normalized
        for legacy_name in (
            "RESEARCH_GRAPH_PROPOSALS",
            "RESEARCH_GRAPH_REVIEWS",
            "RESEARCH_GRAPH_VALIDATIONS",
            "RESEARCH_GRAPH_AUDITS",
            "HUMAN_ACTIVATION_AUTHORIZATIONS",
        )
    )


def test_terminal_job_owns_trusted_assurance_without_graph_agent(
    client,
) -> None:
    workspace_id = f"assurance-{uuid.uuid4().hex}"
    instance = _active_instance(workspace_id=workspace_id)
    job = _succeeded_job(workspace_id=workspace_id)["job"]
    flow_store = agent_flow.get_store()
    agent_id = f"instance:{instance['instance_id']}"
    before = flow_store.count_invocations(
        owner_user_id="alice",
        agent_id=agent_id,
    )

    response = client.get(f"/api/jobs/{job.job_id}")
    assurance = response.get_json()["evidence"]["terminal_assurance"]

    assert response.status_code == 200
    assert assurance["disposition"] == "trusted"
    assert assurance["anomaly_codes"] == []
    after = flow_store.count_invocations(
        owner_user_id="alice",
        agent_id=agent_id,
    )
    assert after == before


def test_terminal_job_anomaly_opens_one_maintenance_case(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    workspace_id = f"assurance-anomaly-{uuid.uuid4().hex}"
    job = _succeeded_job(
        workspace_id=workspace_id,
        worker_exitcode=1,
    )["job"]
    terminal = JobRepository().require(job.job_id, owner="alice")
    with research_graphs.connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        cases = conn.execute(
            """
            SELECT * FROM research_maintenance_cases
            WHERE owner_user_id='alice'
            """
        ).fetchall()

    assert terminal.terminal_assurance is not None
    assert terminal.terminal_assurance.disposition == "maintenance_required"
    assert "succeeded_after_worker_crash" in (
        terminal.terminal_assurance.anomaly_codes
    )
    assert len(cases) == 1
    assert f"job:{job.job_id}" in orjson.loads(
        cases[0]["affected_refs_json"]
    )


@pytest.mark.parametrize(
    "path",
    [
        "/api/research-backend-assurance/evaluate",
        "/api/research-backend-assurance/legacy/verification",
    ],
)
def test_backend_assurance_legacy_posts_point_to_job_evidence_and_case(
    client,
    path,
) -> None:
    response = client.post(path, json={})

    payload = response.get_json()
    assert response.status_code == 410
    assert payload["replacement"]["job_evidence"] == (
        "GET /api/jobs/<job_id> -> evidence.terminal_assurance"
    )
    assert payload["replacement"]["verification"] == "MaintenanceCase"


def test_graph_schema_refuses_unmigrated_backend_assurance_receipts(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        Settings,
        "CACHE_DB_PATH",
        tmp_path / "legacy-receipt.sqlite",
    )
    with research_graphs.connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE research_backend_assurance_receipts (
                receipt_id TEXT PRIMARY KEY
            )
            """
        )

    with pytest.raises(
        RuntimeError,
        match="migrate_backend_assurance",
    ):
        research_graphs.ensure_schema()

    with research_graphs.connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        old_table = conn.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type='table'
              AND name='research_backend_assurance_receipts'
            """
        ).fetchone()
    assert old_table is not None


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
    proposal, _ = _approve_proposal()
    research_graphs.record_validation(
        graph_id="factor-research",
        version=2,
        proposal_id=proposal["proposal_id"],
        actor="alice",
        evidence=_server_validation_evidence(shadow_passed=False),
    )
    with pytest.raises(
        ValueError,
        match="deterministic validation to pass",
    ):
        research_graphs.record_audit(
            graph_id="factor-research",
            version=2,
            proposal_id=proposal["proposal_id"],
            actor="alice",
            disposition="approved",
            grill_evidence=[{"question": "Shadow?", "answer": "Pending"}],
            grill_ref="grill-with-docs:test-shadow-failure",
        )


def test_validation_rejects_a_token_efficient_claim_with_regression(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    research_graphs.register_graph(_draft_graph(), actor="curator-agent")
    proposal, _ = _approve_proposal()

    with pytest.raises(ValueError, match="client token_metrics"):
        research_graphs.record_validation(
            graph_id="factor-research",
            version=2,
            proposal_id=proposal["proposal_id"],
            actor="alice",
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
            proposal_id=proposal["proposal_id"],
            actor="alice",
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
    proposal, _ = _approve_proposal()

    with pytest.raises(ValueError, match=message):
        research_graphs.record_validation(
            graph_id="factor-research",
            version=2,
            proposal_id=proposal["proposal_id"],
            actor="alice",
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
        conversation_ref="auth-conversation:test-review-disagreement",
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
    with pytest.raises(
        ValueError,
        match="independent approval majority",
    ):
        research_graphs.record_validation(
            graph_id="factor-research",
            version=2,
            proposal_id=proposal["proposal_id"],
            actor="alice",
            evidence=_server_validation_evidence(),
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
    research_graphs.record_validation(
        graph_id="factor-research",
        version=2,
        proposal_id=proposal["proposal_id"],
        actor="alice",
        evidence=_server_validation_evidence(),
    )
    research_graphs.record_audit(
        graph_id="factor-research",
        version=2,
        proposal_id=proposal["proposal_id"],
        actor="alice",
        disposition="approved",
        grill_evidence=[{"question": "counterexample?", "answer": "bounded"}],
        grill_ref="grill-with-docs:test-review-disagreement",
    )
    active = _activate()
    assert active["lifecycle"] == "active"


@pytest.mark.parametrize(
    ("scope_drift", "semantic_uncertainty"),
    [(True, False), (False, True)],
)
def test_review_flags_override_an_approved_disposition(
    tmp_path,
    monkeypatch,
    scope_drift,
    semantic_uncertainty,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    research_graphs.register_graph(_draft_graph(), actor="curator-agent")
    proposal = research_graphs.record_proposal(
        graph_id="factor-research",
        version=2,
        owner_user_id="alice",
        actor_agent_id=_agent_execution("proposer")["execution_id"],
        risk_level="L4",
        change_diff={"reason": "flagged review must disagree"},
        evidence_refs=["test:proposal"],
        token_estimate=300,
        conversation_ref="auth-conversation:test-flagged-review",
    )
    review = research_graphs.record_proposal_review(
        proposal_id=proposal["proposal_id"],
        owner_user_id="alice",
        actor_agent_id=_agent_execution("reviewer")["execution_id"],
        disposition="approved",
        scope_drift=scope_drift,
        semantic_uncertainty=semantic_uncertainty,
        evidence_refs=["test:flagged-review"],
    )
    assert review["disposition"] == "approved"

    with pytest.raises(ValueError, match="independent approval majority"):
        research_graphs.record_validation(
            graph_id="factor-research",
            version=2,
            proposal_id=proposal["proposal_id"],
            actor="alice",
            evidence=_server_validation_evidence(),
        )


def test_audited_rollback_moves_only_the_active_pointer(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    research_graphs.register_graph(_draft_graph(), actor="curator-agent")
    proposal, _ = _approve_proposal()
    research_graphs.record_validation(
        graph_id="factor-research",
        version=2,
        proposal_id=proposal["proposal_id"],
        actor="alice",
        evidence=_server_validation_evidence(),
    )
    research_graphs.record_audit(
        graph_id="factor-research",
        version=2,
        proposal_id=proposal["proposal_id"],
        actor="alice",
        disposition="approved",
        grill_evidence=[{"question": "activate?", "answer": "yes"}],
        grill_ref="grill-with-docs:test-first-active",
    )
    first_active = _activate()
    second_draft = _draft_graph()
    second_draft["version"] = 4
    second_draft["parent_version"] = 3
    second_draft["nodes"][0]["purpose"] = "freeze a refined hypothesis"
    second_draft["content_hash"] = _hash(second_draft)
    research_graphs.register_graph(second_draft, actor="curator-agent")
    proposal, _ = _approve_proposal(
        version=4,
        new_hash=second_draft["content_hash"],
    )
    research_graphs.record_validation(
        graph_id="factor-research",
        version=4,
        proposal_id=proposal["proposal_id"],
        actor="alice",
        evidence=_server_validation_evidence(version=4),
    )
    research_graphs.record_audit(
        graph_id="factor-research",
        version=4,
        proposal_id=proposal["proposal_id"],
        actor="alice",
        disposition="approved",
        grill_evidence=[{"question": "activate refined?", "answer": "yes"}],
        grill_ref="grill-with-docs:test-second-active",
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
    proposer = client.post(
        "/api/agent-flow/invocations",
        json=_agent_http_payload("proposer", model_id="test-proposer"),
    )
    reviewer = client.post(
        "/api/agent-flow/invocations",
        json=_agent_http_payload("reviewer", model_id="test-reviewer"),
    )
    assert proposer.status_code == 201
    assert reviewer.status_code == 201
    proposer_id = proposer.get_json()["invocation"]["invocation_id"]
    reviewer_id = reviewer.get_json()["invocation"]["invocation_id"]
    for invocation_id in (proposer_id, reviewer_id):
        settled = client.post(
            f"/api/agent-flow/invocations/{invocation_id}/settle",
            json={
                "input_tokens": 10,
                "output_tokens": 5,
                "provider_request_id": uuid.uuid4().hex,
            },
        )
        assert settled.status_code == 200
    proposal = client.post(
        "/api/research-graphs/factor-research/versions/2/proposals",
        json={
            "agent_execution_id": proposer_id,
            "risk_level": "L4",
            "change_diff": {"reason": "HTTP identity-chain test"},
            "evidence_refs": ["test:http-proposal"],
            "token_estimate": 250,
            "conversation_ref": "auth-conversation:http-graph-test",
        },
    )
    assert proposal.status_code == 201
    review = client.post(
        "/api/research-graph-proposals/"
        f"{proposal.get_json()['proposal']['proposal_id']}/reviews",
        json={
            "agent_execution_id": reviewer_id,
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
            **_server_validation_evidence(),
            "proposal_id": proposal.get_json()["proposal"]["proposal_id"],
        },
    )
    assert validated.status_code == 201

    audited = client.post(
        "/api/research-graphs/factor-research/versions/2/audit",
        json={
            "proposal_id": proposal.get_json()["proposal"]["proposal_id"],
            "disposition": "approved",
            "grill_ref": "grill-with-docs:http-graph-test",
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
    diff_hash = hashlib.sha256(orjson.dumps(
        {"reason": "HTTP identity-chain test"},
        option=orjson.OPT_SORT_KEYS,
    )).hexdigest()
    authorization = client.post(
        "/api/research-human-activation-authorizations",
        json={
            "graph_id": "factor-research",
            "graph_version": 2,
            "graph_hash": graph["content_hash"],
            "proposal_id": proposal_row["proposal_id"],
            "diff_hash": diff_hash,
            "conversation_ref": "auth-conversation:http-graph-test",
            "approval_ref": "auth-conversation-event:http-approval",
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
    proposal, _ = _approve_proposal()
    research_graphs.record_validation(
        graph_id="factor-research",
        version=2,
        proposal_id=proposal["proposal_id"],
        actor="alice",
        evidence=_server_validation_evidence(),
    )
    research_graphs.record_audit(
        graph_id="factor-research",
        version=2,
        proposal_id=proposal["proposal_id"],
        actor="alice",
        disposition="approved",
        grill_evidence=[{"question": "isolated?", "answer": "yes"}],
        grill_ref="grill-with-docs:test-branch-isolation",
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
            "agent_invocation_ids": [_commit_usage(
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
    assert len(selects) == 2
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
    proposal, _ = _approve_proposal()
    research_graphs.record_validation(
        graph_id="factor-research",
        version=2,
        proposal_id=proposal["proposal_id"],
        actor="alice",
        evidence=_server_validation_evidence(),
    )
    research_graphs.record_audit(
        graph_id="factor-research",
        version=2,
        proposal_id=proposal["proposal_id"],
        actor="alice",
        disposition="approved",
        grill_evidence=[{"question": "local?", "answer": "yes"}],
        grill_ref="grill-with-docs:test-local-resolution",
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
    agent_flow.get_store().configure_token_limit(
        owner_user_id="alice",
        agent_id=f"instance:{instance['instance_id']}",
        token_limit=12,
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
            "agent_invocation_ids": [_commit_usage(
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
        "authority": "normalized_agent_invocations",
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
    store = agent_flow.get_store()
    store.configure_token_limit(
        owner_user_id="alice",
        agent_id="hard-limit",
        token_limit=100,
    )
    granted = store.reserve_invocation(
        owner_user_id="alice",
        agent_id="hard-limit",
        actor_role="reviewer",
        authority_scope="local_research",
        purpose="review",
        runtime_id="test-runtime",
        model_id="test-model",
        max_input_tokens=60,
        max_output_tokens=20,
        agent_principal_hash="a" * 64,
        lineage_hash="b" * 64,
    )

    with pytest.raises(ValueError, match="agent_budget_exhausted"):
        store.reserve_invocation(
            owner_user_id="alice",
            agent_id="hard-limit",
            actor_role="reviewer",
            authority_scope="local_research",
            purpose="review",
            runtime_id="test-runtime",
            model_id="test-model",
            max_input_tokens=20,
            max_output_tokens=10,
            agent_principal_hash="c" * 64,
            lineage_hash="d" * 64,
        )
    with pytest.raises(ValueError, match="agent_principal_hash"):
        store.reserve_invocation(
            owner_user_id="alice",
            agent_id="hard-limit",
            actor_role="reviewer",
            authority_scope="local_research",
            purpose="review",
            runtime_id="test-runtime",
            model_id="test-model",
            max_input_tokens=10,
            max_output_tokens=5,
            agent_principal_hash="forged",
            lineage_hash="d" * 64,
        )

    released = store.release_invocation(
        owner_user_id="alice",
        invocation_or_reservation_id=granted["invocation_id"],
    )
    budget = store.load_current_budget_period(
        owner_user_id="alice",
        agent_id="hard-limit",
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
    proposal, _ = _approve_proposal()
    research_graphs.record_validation(
        graph_id="factor-research",
        version=2,
        proposal_id=proposal["proposal_id"],
        actor="alice",
        evidence=_server_validation_evidence(),
    )
    research_graphs.record_audit(
        graph_id="factor-research",
        version=2,
        proposal_id=proposal["proposal_id"],
        actor="alice",
        disposition="approved",
        grill_evidence=[{"question": "conditional?", "answer": "bounded"}],
        grill_ref="grill-with-docs:test-condition-resolution",
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
