from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import sqlite3
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
from server.services.agent_flow.verified_usage import VerifiedProviderUsage
from server.services.research_graph import versions as graph_versions
from server.services.research_graph import active_pointer
from server.services.research_graph.branch import (
    context as branch_context,
    next_packet as branch_next_packet,
    runtime as branch_runtime,
    transition as branch_transition,
)
from server.services.research_graph.research_cycle.replay import (
    validate_research_cycle_checkpoint,
)
from server.services.research_graph.branch.repository import (
    load_instance_branch_row,
)
from server.services.research_graph.shadow_trace import replay_shadow_trace
from server.services.research_graph.shadow_tokens import shadow_token_contract
from server.services.research_graph.protocol import MAX_AGENT_TRANSITION_BYTES


def _initialize_graph_db(tmp_path, monkeypatch) -> None:
    """Run graph migrations explicitly before exercising request hot paths."""
    monkeypatch.setattr(
        Settings,
        "CACHE_DB_PATH",
        tmp_path / "graphs.sqlite",
    )
    research_graphs.ensure_schema()
    JobRepository().ensure_schema()
    monkeypatch.setenv(
        "RESEARCH_HUMAN_ACTIVATION_SECRET",
        "test-human-activation-secret",
    )
    agent_flow.clear_store_cache()


def test_next_packet_describes_server_action_contract_on_demand() -> None:
    candidate = branch_next_packet._edge_candidate(
        {
            "edge_id": "semantics",
            "to_node": "validation_design",
            "edge_type": "conditional",
            "server_action": "bind_factor_semantics",
        },
        open_gap_ids=[],
        undetermined_ids=[],
    )

    assert candidate["action_contract"] == {
        "request_field": "factor_semantics_request",
        "contract_command": (
            "factortester research step inspect "
            "<instance-id> <branch-id> --output <file>"
        ),
        "submission": "include the request only in transition evidence",
    }


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
    *,
    pointer_action: str = "activate_graph",
    pointer_from_version: int = 0,
    pointer_reason: str = "",
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
        pointer_action=pointer_action,
        pointer_from_version=pointer_from_version,
        pointer_reason=pointer_reason,
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
    pointer_action: str = "activate_graph",
    pointer_from_version: int = 0,
    pointer_reason: str = "",
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
        pointer_action=pointer_action,
        pointer_from_version=pointer_from_version,
        pointer_reason=pointer_reason,
    )


def _activate(graph_version: int = 2) -> dict:
    authorization = _human_authorization(graph_version=graph_version)
    return research_graphs.activate_graph(
        graph_id="factor-research",
        source_version=graph_version,
        actor="alice",
        human_authorization_id=authorization["authorization_id"],
    )


def _authorize_rollback(
    *,
    from_version: int,
    target_version: int,
    reason: str,
    validation_evidence: dict | None = None,
) -> dict:
    target = research_graphs.load_graph(
        graph_id="factor-research",
        version=target_version,
    )
    proposal, _ = _approve_proposal(
        version=target_version,
        new_hash=target["content_hash"],
        pointer_action="rollback_graph_pointer",
        pointer_from_version=from_version,
        pointer_reason=reason,
    )
    research_graphs.record_validation(
        graph_id="factor-research",
        version=target_version,
        proposal_id=proposal["proposal_id"],
        actor="alice",
        evidence=(
            validation_evidence
            if validation_evidence is not None
            else _server_validation_evidence(version=target_version)
        ),
    )
    research_graphs.record_audit(
        graph_id="factor-research",
        version=target_version,
        proposal_id=proposal["proposal_id"],
        actor="alice",
        disposition="approved",
        grill_evidence=[{
            "question": "pointer-only rollback?",
            "answer": "approved for exact target",
        }],
        grill_ref=f"grill-with-docs:test-pointer-rollback-{uuid.uuid4().hex}",
    )
    return _human_authorization(
        graph_version=target_version,
        pointer_action="rollback_graph_pointer",
        pointer_from_version=from_version,
        pointer_reason=reason,
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
    resolution = _capability_resolution(
        node_id="hypothesis",
        product_group="equities",
        capability_ids=["research-hypothesis.preregister"],
    )
    return research_graphs.create_graph_instance(
        graph_id="factor-research",
        owner="alice",
        product_group="equities",
        workspace_id=workspace_id,
        capability_resolution=resolution,
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


def _capability_resolution(
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
    return {
        "node_id": node_id,
        "bindings": bindings,
        "gaps": [],
        "triggered_conditional_bindings": triggered_bindings,
        "undetermined_conditions": undetermined_conditions or [],
    }


def _commit_scope_usage(
    *,
    scope_id: str,
    input_tokens: int,
    output_tokens: int,
    provider_actual: bool = True,
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
        input_tokens=input_tokens if provider_actual else None,
        output_tokens=output_tokens if provider_actual else None,
        provider_request_id=uuid.uuid4().hex if provider_actual else "",
    )
    return invocation["invocation_id"]


def _commit_usage(
    *,
    instance_id: str,
    input_tokens: int,
    output_tokens: int,
    provider_actual: bool = True,
) -> str:
    return _commit_scope_usage(
        scope_id=f"instance:{instance_id}",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        provider_actual=provider_actual,
    )


def _commit_shadow_usage(
    *,
    agent_id: str,
    task_ref: str,
    lineage_hash: str,
    input_hash: str,
    input_tokens: int,
    output_tokens: int,
    verified: bool = True,
) -> str:
    store = agent_flow.get_store()
    invocation = store.reserve_invocation(
        owner_user_id="alice",
        agent_id=agent_id,
        actor_role="researcher",
        authority_scope="local_research",
        task_ref=task_ref,
        purpose="active Graph token shadow",
        runtime_id="test-runtime",
        model_id="test-model",
        max_input_tokens=input_tokens,
        max_output_tokens=output_tokens,
        agent_principal_hash=hashlib.sha256(agent_id.encode()).hexdigest(),
        lineage_hash=lineage_hash,
        input_hash=input_hash,
    )

    class Verifier:
        def verify(self, receipt, *, reservation):
            return VerifiedProviderUsage(
                provider_id="test-provider",
                provider_request_id=receipt,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=0,
                provider_attestation=f"signed:{receipt}",
                launcher_attestation="verified-by:test-provider@1",
            )

    if verified:
        store.settle_verified_invocation(
            owner_user_id="alice",
            invocation_id=invocation["invocation_id"],
            receipt=f"receipt:{uuid.uuid4().hex}",
            expected_provider_id="test-provider",
            verifier=Verifier(),
        )
    else:
        store.settle_invocation(
            owner_user_id="alice",
            invocation_id=invocation["invocation_id"],
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            provider_request_id=f"unverified:{uuid.uuid4().hex}",
            provider_attestation="caller-controlled",
        )
    return invocation["invocation_id"]


def _server_validation_evidence(
    *,
    version: int = 2,
    graph_tokens: int = 80,
    baseline_tokens: int = 100,
    matching_run_spec: bool = True,
    launch_subagent: bool = False,
    fallback_graph_usage: bool = False,
    extra_shadow_usage: bool = False,
    bootstrap_legacy_replay: bool = True,
) -> dict:
    target_graph = research_graphs.load_graph(
        graph_id="factor-research",
        version=version,
    )
    parent_version = int(target_graph.get("parent_version") or 0)
    if parent_version < 1:
        raise AssertionError("shadow validation requires a parent Graph")
    with research_graphs.connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        previous_pointer = conn.execute(
            """
            SELECT version, activated_by, activated_at
            FROM active_research_graphs WHERE graph_id='factor-research'
            """
        ).fetchone()
        conn.execute(
            """
            INSERT INTO active_research_graphs (
                graph_id, version, activated_by, activated_at
            ) VALUES ('factor-research', ?, 'alice', 1.0)
            ON CONFLICT(graph_id) DO UPDATE SET version=excluded.version
            """,
            (parent_version,),
        )
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
    resolution = _capability_resolution(
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
        capability_resolution=resolution,
        shadow_graph_version=version,
        shadow_run_id=graph_run["run_id"],
        shadow_proposal_id=_latest_proposal(
            graph_version=version,
        )["proposal_id"],
    )
    with research_graphs.connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        if previous_pointer is None:
            conn.execute(
                """
                DELETE FROM active_research_graphs
                WHERE graph_id='factor-research'
                """
            )
        else:
            conn.execute(
                """
                UPDATE active_research_graphs
                SET version=?, activated_by=?, activated_at=?
                WHERE graph_id='factor-research'
                """,
                (
                    int(previous_pointer["version"]),
                    str(previous_pointer["activated_by"]),
                    float(previous_pointer["activated_at"]),
                ),
            )
    flow_store = agent_flow.get_store()
    flow_store.configure_token_limit(
        owner_user_id="alice",
        agent_id=f"instance:{instance['instance_id']}",
        token_limit=1000,
    )
    branch_id = instance["branches"][0]["branch_id"]
    if (
        bootstrap_legacy_replay
        and int(target_graph.get("schema_version") or 1) < 2
    ):
        branch_id = research_graphs.fork_graph_branch(
            instance_id=instance["instance_id"],
            source_branch_id=branch_id,
            owner="alice",
            label="legacy-shadow-replay-bootstrap",
        )["branch_id"]
    token_contract = shadow_token_contract(
        graph_id="factor-research",
        version=version,
        instance_id=instance["instance_id"],
        branch_id=branch_id,
        graph_run_id=graph_run["run_id"],
        baseline_run_id=baseline_run["run_id"],
        run_spec_hash=graph_run["run_spec_hash"],
    )
    if graph_tokens:
        graph_binding = token_contract["graph"]
        _commit_shadow_usage(
            agent_id=graph_binding["agent_id"],
            task_ref=graph_binding["task_ref"],
            lineage_hash=token_contract["comparison_hash"],
            input_hash=token_contract["input_hash"],
            input_tokens=max(graph_tokens - 10, 0),
            output_tokens=min(graph_tokens, 10),
            verified=not fallback_graph_usage,
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
        baseline_binding = token_contract["baseline"]
        _commit_shadow_usage(
            agent_id=baseline_binding["agent_id"],
            task_ref=baseline_binding["task_ref"],
            lineage_hash=token_contract["comparison_hash"],
            input_hash=token_contract["input_hash"],
            input_tokens=max(baseline_tokens - 10, 0),
            output_tokens=min(baseline_tokens, 10),
        )
    if extra_shadow_usage:
        _commit_shadow_usage(
            agent_id=token_contract["graph"]["agent_id"],
            task_ref="unapproved-extra-shadow-call",
            lineage_hash=token_contract["comparison_hash"],
            input_hash=token_contract["input_hash"],
            input_tokens=1,
            output_tokens=1,
        )
    return {
        "shadow_comparison_refs": {
            "routine_instance_id": instance["instance_id"],
            "routine_branch_id": branch_id,
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


def _observed_graph() -> dict:
    graph = deepcopy(_draft_graph())
    graph.update({
        "version": 1,
        "lifecycle": "observed",
        "parent_version": 0,
    })
    graph["content_hash"] = _hash(graph)
    return graph


def _prepare_shadow_start() -> tuple[dict, dict]:
    observed = research_graphs.register_graph(
        _observed_graph(),
        actor="curator-agent",
    )
    draft = research_graphs.register_graph(
        _draft_graph(),
        actor="curator-agent",
    )
    with research_graphs.connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO active_research_graphs (
                graph_id, version, activated_by, activated_at
            ) VALUES (?, ?, ?, ?)
            """,
            ("factor-research", 1, "alice", 1.0),
        )
    run = research_runs.create_run(
        owner="alice",
        workspace_id="workspace-1",
        configuration_id=f"shadow-{uuid.uuid4().hex}",
        configuration_revision=1,
        run_spec={"workspace_id": "workspace-1", "factor": "test"},
    )
    return observed | {"draft": draft}, run


def _open_shadow_proposal(*, version: int = 2) -> dict:
    proposer = _agent_execution("proposer")
    return research_graphs.record_proposal(
        graph_id="factor-research",
        version=version,
        owner_user_id="alice",
        actor_agent_id=proposer["execution_id"],
        risk_level="L4",
        change_diff={"reason": f"shadow-test-v{version}"},
        evidence_refs=["test:shadow-eligibility"],
        token_estimate=100,
        conversation_ref="auth-conversation:test-shadow-eligibility",
    )


def _start_shadow(*, run_id: str, proposal_id: str) -> dict:
    return research_graphs.create_graph_instance(
        graph_id="factor-research",
        owner="alice",
        product_group="equities",
        workspace_id="workspace-1",
        capability_resolution=_capability_resolution(
            node_id="hypothesis",
            product_group="equities",
            capability_ids=["research-hypothesis.preregister"],
            graph_version=2,
            shadow_mode=True,
        ),
        shadow_graph_version=2,
        shadow_run_id=run_id,
        shadow_proposal_id=proposal_id,
    )


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


def test_shadow_start_requires_an_explicit_activation_proposal(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    _, run = _prepare_shadow_start()

    with pytest.raises(
        research_graphs.GraphActivationBlocked,
        match="shadow proposal",
    ):
        research_graphs.create_graph_instance(
            graph_id="factor-research",
            owner="alice",
            product_group="equities",
            workspace_id="workspace-1",
            capability_resolution=_capability_resolution(
                node_id="hypothesis",
                product_group="equities",
                capability_ids=["research-hypothesis.preregister"],
                graph_version=2,
                shadow_mode=True,
            ),
            shadow_graph_version=2,
            shadow_run_id=run["run_id"],
        )

    with research_graphs.connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM research_graph_instances"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM research_work_packages"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM research_graph_branches"
        ).fetchone()[0] == 0


def test_shadow_start_accepts_direct_child_with_matching_open_proposal(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    _, run = _prepare_shadow_start()
    proposal = _open_shadow_proposal()

    instance = _start_shadow(
        run_id=run["run_id"],
        proposal_id=proposal["proposal_id"],
    )

    assert instance["mode"] == "shadow"
    assert instance["graph_version"] == 2


def test_shadow_start_accepts_matching_proposal_without_parent_restriction(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    _, run = _prepare_shadow_start()
    proposal = _open_shadow_proposal()
    with research_graphs.connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute(
            """
            UPDATE active_research_graphs SET version=2
            WHERE graph_id='factor-research'
            """
        )

    instance = _start_shadow(
        run_id=run["run_id"],
        proposal_id=proposal["proposal_id"],
    )

    assert instance["mode"] == "shadow"
    assert instance["graph_version"] == 2


@pytest.mark.parametrize(
    "proposal_mutation",
    ["wrong_owner", "wrong_target", "wrong_action", "consumed"],
)
def test_shadow_start_rejects_a_nonmatching_or_consumed_proposal(
    tmp_path,
    monkeypatch,
    proposal_mutation,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    _, run = _prepare_shadow_start()
    if proposal_mutation == "wrong_target":
        graph = deepcopy(_draft_graph())
        graph.update({"version": 3, "parent_version": 2})
        graph["content_hash"] = _hash(graph)
        research_graphs.register_graph(graph, actor="curator-agent")
        proposal = _open_shadow_proposal(version=3)
    elif proposal_mutation == "wrong_action":
        proposer = _agent_execution("proposer")
        proposal = research_graphs.record_proposal(
            graph_id="factor-research",
            version=2,
            owner_user_id="alice",
            actor_agent_id=proposer["execution_id"],
            risk_level="L4",
            change_diff={"reason": "wrong shadow action"},
            evidence_refs=["test:wrong-action"],
            token_estimate=100,
            conversation_ref="auth-conversation:test-wrong-action",
            pointer_action="rollback_graph_pointer",
            pointer_from_version=1,
            pointer_reason="test rollback is not shadow authorization",
        )
    else:
        proposal = _open_shadow_proposal()
        with research_graphs.connect_sqlite(Settings.CACHE_DB_PATH) as conn:
            if proposal_mutation == "wrong_owner":
                conn.execute(
                    """
                    UPDATE research_maintenance_cases
                    SET owner_user_id='bob' WHERE case_id=?
                    """,
                    (proposal["proposal_id"],),
                )
            else:
                conn.execute(
                    """
                    UPDATE research_maintenance_cases
                    SET status='resolved', closed_at=2.0 WHERE case_id=?
                    """,
                    (proposal["proposal_id"],),
                )

    with pytest.raises(research_graphs.GraphActivationBlocked):
        _start_shadow(
            run_id=run["run_id"],
            proposal_id=proposal["proposal_id"],
        )

    with research_graphs.connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM research_graph_instances"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM research_work_packages"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM research_graph_branches"
        ).fetchone()[0] == 0


def test_shadow_start_fails_closed_if_active_pointer_changes(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    _, run = _prepare_shadow_start()
    proposal = _open_shadow_proposal()
    require_eligibility = branch_runtime.require_shadow_eligibility

    def move_pointer_after_check(conn, **kwargs):
        result = require_eligibility(conn, **kwargs)
        conn.execute(
            """
            UPDATE active_research_graphs SET version=2
            WHERE graph_id='factor-research'
            """
        )
        return result

    monkeypatch.setattr(
        branch_runtime,
        "require_shadow_eligibility",
        move_pointer_after_check,
    )
    with pytest.raises(
        research_graphs.GraphActivationBlocked,
        match="pointer changed",
    ):
        _start_shadow(
            run_id=run["run_id"],
            proposal_id=proposal["proposal_id"],
        )

    with research_graphs.connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        assert conn.execute(
            "SELECT version FROM active_research_graphs"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM research_graph_instances"
        ).fetchone()[0] == 0


def test_graph_continuation_routes_preserve_exact_target(
    client,
    monkeypatch,
) -> None:
    calls: list[tuple[str, dict]] = []

    def preview(**kwargs):
        calls.append(("preview", kwargs))
        return {"target_hash": "c" * 64}

    def continue_branch(**kwargs):
        calls.append(("continue", kwargs))
        return {
            "instance_id": "instance-v6",
            "graph_version": 6,
            "branches": [{"branch_id": "branch-v6"}],
        }

    monkeypatch.setattr(
        research_graphs,
        "preview_graph_continuation",
        preview,
    )
    monkeypatch.setattr(
        research_graphs,
        "continue_graph_branch",
        continue_branch,
    )
    preview_response = client.post(
        "/api/research-graph-instances/instance-v5"
        "/branches/branch-v5/continuation-preview",
        json={"target_graph_version": 6, "job_id": "job-1"},
    )
    continue_response = client.post(
        "/api/research-graph-instances/instance-v5"
        "/branches/branch-v5/continuations",
        json={
            "target_graph_version": 6,
            "job_id": "job-1",
            "expected_target_hash": "c" * 64,
            "execution_mode": "live",
        },
    )

    assert preview_response.status_code == 200
    assert continue_response.status_code == 201
    assert calls == [
        ("preview", {
            "source_instance_id": "instance-v5",
            "source_branch_id": "branch-v5",
            "owner": "alice",
            "target_graph_version": 6,
            "job_id": "job-1",
            "execution_mode": "live",
            "shadow_run_id": "",
            "shadow_proposal_id": "",
        }),
        ("continue", {
            "source_instance_id": "instance-v5",
            "source_branch_id": "branch-v5",
            "owner": "alice",
            "target_graph_version": 6,
            "job_id": "job-1",
            "expected_target_hash": "c" * 64,
            "execution_mode": "live",
            "shadow_run_id": "",
            "shadow_proposal_id": "",
        }),
    ]


def test_shadow_start_http_forwards_explicit_proposal_id(
    client,
    monkeypatch,
) -> None:
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return {"instance_id": "shadow-instance"}

    monkeypatch.setattr(research_graphs, "create_graph_instance", create)
    response = client.post(
        "/api/research-graph-instances",
        json={
            "graph_id": "factor-research",
            "product_group": "equities",
            "workspace_id": "workspace-1",
            "title": "MaxA research",
            "capability_resolution": {},
            "shadow_graph_version": 9,
            "shadow_run_id": "run-shadow",
            "shadow_proposal_id": "proposal-v9",
        },
    )

    assert response.status_code == 201
    assert captured["shadow_proposal_id"] == "proposal-v9"
    assert captured["title"] == "MaxA research"


def test_graph_versions_are_immutable_and_activation_moves_only_pointer(
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
    assert active["version"] == 2
    assert active["lifecycle"] == "draft"
    assert active["content_hash"] == draft["content_hash"]
    assert active["active_pointer"]["version"] == 2
    assert active["is_active"] is True
    assert len(research_graphs.list_graph_versions(
        graph_id="factor-research",
    )) == 1
    assert research_graphs.load_active_graph(
        graph_id="factor-research"
    )["content_hash"] == active["content_hash"]


def test_branch_transition_rejects_legacy_evidence_before_database_access(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    instance = _active_instance(workspace_id="workspace-legacy-denial")
    branch = instance["branches"][0]
    original_connect = branch_transition.connect_sqlite
    monkeypatch.setattr(
        branch_transition,
        "connect_sqlite",
        lambda *_args, **_kwargs: pytest.fail(
            "legacy evidence reached the database"
        ),
    )

    with pytest.raises(
        ValueError,
        match="legacy evidence is unavailable to Agents",
    ):
        research_graphs.advance_graph_branch(
            instance_id=instance["instance_id"],
            branch_id=branch["branch_id"],
            owner="alice",
            edge_id="hypothesis__resolution",
            evidence={
                "hypothesis_frozen": True,
                "evidence_envelope": {
                    "schema_version": 1,
                    "envelope_id": "legacy-1",
                    "envelope_hash": "a" * 64,
                    "decision": "continue",
                    "metric_refs": ["metric:private"],
                    "artifact_refs": ["artifact:private"],
                },
            },
        )

    monkeypatch.setattr(
        branch_transition,
        "connect_sqlite",
        original_connect,
    )


def test_branch_advance_http_rejects_legacy_evidence(
    client,
) -> None:
    instance = _active_instance(workspace_id="workspace-legacy-http")
    branch = instance["branches"][0]

    response = client.post(
        (
            f"/api/research-graph-instances/{instance['instance_id']}"
            f"/branches/{branch['branch_id']}/node/advance"
        ),
        json={
            "edge_id": "hypothesis__resolution",
            "evidence": {
                "hypothesis_frozen": True,
                "evidence_envelope": {
                    "schema_version": 1,
                    "envelope_id": "legacy-http",
                    "envelope_hash": "a" * 64,
                    "decision": "continue",
                    "artifact_refs": ["artifact:private"],
                },
            },
        },
    )

    assert response.status_code == 409
    assert "legacy evidence is unavailable to Agents" in (
        response.get_json()["error"]
    )


def test_branch_transition_rejects_decision_inside_current_evidence(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    instance = _active_instance(workspace_id="workspace-v2-factual")
    branch = instance["branches"][0]
    monkeypatch.setattr(
        branch_transition,
        "connect_sqlite",
        lambda *_args, **_kwargs: pytest.fail(
            "non-factual evidence reached the database"
        ),
    )

    with pytest.raises(
        ValueError,
        match="factual evidence must not contain decision",
    ):
        research_graphs.advance_graph_branch(
            instance_id=instance["instance_id"],
            branch_id=branch["branch_id"],
            owner="alice",
            edge_id="hypothesis__resolution",
            evidence={
                "hypothesis_frozen": True,
                "evidence_envelope": {
                    "schema_version": 2,
                    "envelope_id": "evidence-2",
                    "evidence_kind": "analysis",
                    "source_refs": ["analysis:2"],
                    "identity_refs": {},
                    "metric_refs": [],
                    "artifact_refs": [],
                    "hypotheses_tested": 1,
                    "stop_condition": None,
                    "limitations": [],
                    "conflicts": [],
                    "decision": "supported_in_scope",
                },
            },
        )


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
    consume_activation = (
        active_pointer.pointer_gate.consume_activation
    )

    def consume_then_fail(conn, **kwargs):
        consume_activation(conn, **kwargs)
        raise sqlite3.OperationalError("injected pointer write failure")

    monkeypatch.setattr(
        active_pointer.pointer_gate,
        "consume_activation",
        consume_then_fail,
    )
    with pytest.raises(sqlite3.OperationalError, match="pointer write failure"):
        research_graphs.activate_graph(
            graph_id="factor-research",
            source_version=2,
            actor="alice",
            human_authorization_id=authorization["authorization_id"],
        )
    with research_graphs.connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        gate_after_failure = conn.execute(
            """
            SELECT status FROM research_maintenance_cases
            WHERE case_id=?
            """,
            (authorization["authorization_id"],),
        ).fetchone()
        pointer_after_failure = conn.execute(
            """
            SELECT version FROM active_research_graphs
            WHERE graph_id='factor-research'
            """
        ).fetchone()
    assert gate_after_failure["status"] == "blocked"
    assert pointer_after_failure is None
    monkeypatch.setattr(
        active_pointer.pointer_gate,
        "consume_activation",
        consume_activation,
    )
    with research_graphs.connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO research_graph_instances (
                instance_id, work_package_id, owner,
                created_by_profile_ref, current_owner_profile_ref,
                graph_id, graph_version, product_group, workspace_id,
                mode, shadow_run_id, created_at
            ) VALUES (
                'draft-continuation', 'work-package-1', 'alice',
                'profile:maxa', 'profile:maxa',
                'factor-research', 2, 'neutral', 'workspace-1',
                'shadow', '', 1
            )
            """
        )
        conn.execute(
            """
            INSERT INTO research_graph_instances (
                instance_id, work_package_id, owner,
                created_by_profile_ref, current_owner_profile_ref,
                graph_id, graph_version, product_group, workspace_id,
                mode, shadow_run_id, created_at
            ) VALUES (
                'activation-shadow', 'shadow-package', 'alice',
                'profile:server', 'profile:server',
                'factor-research', 2, 'neutral', 'workspace-1',
                'shadow', 'run-shadow-1', 1
            )
            """
        )
    active = research_graphs.activate_graph(
        graph_id="factor-research",
        source_version=2,
        actor="alice",
        human_authorization_id=authorization["authorization_id"],
    )
    assert active["lifecycle"] == "draft"
    assert active["active_pointer"]["version"] == 2
    assert active["promoted_continuation_count"] == 1
    with research_graphs.connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        gate = conn.execute(
            """
            SELECT status, latest_result_ref
            FROM research_maintenance_cases
            WHERE case_id=?
            """,
            (authorization["authorization_id"],),
        ).fetchone()
        modes = dict(conn.execute(
            """
            SELECT instance_id, mode FROM research_graph_instances
            WHERE instance_id IN ('draft-continuation', 'activation-shadow')
            """
        ).fetchall())
    assert gate["status"] == "resolved"
    assert gate["latest_result_ref"].startswith("active-graph:")
    assert modes == {
        "draft-continuation": "live",
        "activation-shadow": "shadow",
    }


def test_activation_preflight_exposes_recoverable_public_proposal(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    research_graphs.register_graph(_draft_graph(), actor="curator-agent")
    proposal, _ = _approve_proposal()

    preflight = research_graphs.activation_preflight(
        graph_id="factor-research",
        version=2,
        owner_user_id="alice",
    )

    assert preflight == {
        "graph_id": "factor-research",
        "active_version": None,
        "target_version": 2,
        "rollback_version": None,
        "ready_for_human_authorization": False,
        "completed_gates": ["independent_review"],
        "missing_gates": [
            "deterministic_validation",
            "grill_audit",
        ],
        "already_active": False,
        "proposal_id": proposal["proposal_id"],
        "next_command": (
            "factortester research-graph proposal "
            f"{proposal['proposal_id']}"
        ),
    }


def test_activation_preflight_reports_missing_proposal_as_a_gate(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    research_graphs.register_graph(_draft_graph(), actor="curator-agent")

    preflight = research_graphs.activation_preflight(
        graph_id="factor-research",
        version=2,
        owner_user_id="alice",
    )

    assert preflight["ready_for_human_authorization"] is False
    assert preflight["completed_gates"] == []
    assert preflight["missing_gates"] == ["activation_proposal"]
    assert "proposal_id" not in preflight
    assert "next_command" not in preflight


def test_proposal_review_packet_exposes_exact_target_without_agent_ids(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    draft = _draft_graph()
    draft["change_manifest"] = {
        "changes": [{"change_id": "change.review-packet"}],
    }
    draft["content_hash"] = _hash(draft)
    graph = research_graphs.register_graph(
        draft,
        actor="curator-agent",
    )
    proposer = _agent_execution("proposer")
    proposal = research_graphs.record_proposal(
        graph_id="factor-research",
        version=2,
        owner_user_id="alice",
        actor_agent_id=proposer["execution_id"],
        risk_level="L4",
        change_diff={
            "old_hash": "observed",
            "new_hash": graph["content_hash"],
            "reason": "review the exact immutable draft",
            "rollback_target": 1,
        },
        evidence_refs=["test:proposal", "git:commit:abc123"],
        token_estimate=500,
        conversation_ref="auth-conversation:test-proposal-packet",
    )

    packet = research_graphs.load_proposal_review_packet(
        owner_user_id="alice",
        proposal_id=proposal["proposal_id"],
    )

    assert packet["proposal"] == {
        "proposal_id": proposal["proposal_id"],
        "action": "activate_graph",
        "diff_hash": proposal["diff_hash"],
        "conversation_ref": "auth-conversation:test-proposal-packet",
        "status": "claimed",
        "created_at": proposal["created_at"],
        "evidence_refs": ["test:proposal", "git:commit:abc123"],
    }
    assert packet["target_graph"] == {
        "graph_id": "factor-research",
        "version": 2,
        "content_hash": graph["content_hash"],
        "parent_version": 1,
        "lifecycle": "draft",
        "change_manifest": graph["change_manifest"],
    }
    assert packet["gate_readiness"]["independent_review"] is False
    assert packet["review_contract"][
        "requires_independent_principal_and_lineage"
    ] is True
    rendered = json.dumps(packet)
    assert proposer["execution_id"] not in rendered
    assert "gate-target-hash:" not in rendered


def test_activation_preflight_http_returns_compact_readiness(client) -> None:
    created = client.post("/api/research-graphs/versions", json={
        "graph": _draft_graph(),
    })
    assert created.status_code == 201
    _approve_proposal()

    response = client.get(
        "/api/research-graphs/factor-research/versions/2/activation"
    )

    assert response.status_code == 200
    payload = response.get_json()["activation"]
    assert payload["target_version"] == 2
    assert payload["completed_gates"] == ["independent_review"]
    assert payload["missing_gates"] == [
        "deterministic_validation",
        "grill_audit",
    ]
    assert payload["proposal_id"]
    assert payload["next_command"] == (
        "factortester research-graph proposal "
        f"{payload['proposal_id']}"
    )
    assert "content_hash" not in payload


def test_proposal_review_packet_http_is_structured_and_read_only(client) -> None:
    draft = _draft_graph()
    draft["change_manifest"] = {
        "changes": [{"change_id": "change.http-review-packet"}],
    }
    draft["content_hash"] = _hash(draft)
    created = client.post("/api/research-graphs/versions", json={
        "graph": draft,
    })
    assert created.status_code == 201
    proposer = _agent_execution("proposer")
    proposal = research_graphs.record_proposal(
        graph_id="factor-research",
        version=2,
        owner_user_id="alice",
        actor_agent_id=proposer["execution_id"],
        risk_level="L4",
        change_diff={
            "old_hash": "observed",
            "new_hash": created.get_json()["graph"]["content_hash"],
            "reason": "review over the authenticated API",
            "rollback_target": 1,
        },
        evidence_refs=["test:http-proposal"],
        token_estimate=500,
        conversation_ref="auth-conversation:test-http-proposal",
    )

    response = client.get(
        f"/api/research-graph-proposals/{proposal['proposal_id']}"
    )

    assert response.status_code == 200
    packet = response.get_json()["proposal_review"]
    assert packet["proposal"]["proposal_id"] == proposal["proposal_id"]
    assert packet["target_graph"]["version"] == 2
    assert packet["target_graph"]["change_manifest"]
    assert packet["review_contract"]["command"].startswith(
        "factortester research-graph review "
    )


def test_activation_http_derives_exact_gate_and_returns_compact_receipt(
    client,
) -> None:
    created = client.post("/api/research-graphs/versions", json={
        "graph": _draft_graph(),
    })
    assert created.status_code == 201
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
        grill_ref="grill-with-docs:test-orchestrated-activation",
    )

    response = client.post(
        "/api/research-graphs/factor-research/versions/2/activation",
        json={
            "approval_ref": (
                "auth-conversation-event:test-orchestrated-activation"
            ),
        },
    )

    assert response.status_code == 201
    receipt = response.get_json()["activation"]
    assert receipt["graph_id"] == "factor-research"
    assert receipt["from_version"] is None
    assert receipt["to_version"] == 2
    assert receipt["rollback_version"] is None
    assert receipt["already_active"] is False
    assert receipt["promoted_continuation_count"] == 0
    assert "nodes" not in receipt
    assert "content_hash" not in receipt
    assert research_graphs.load_active_graph(
        graph_id="factor-research"
    )["version"] == 2

    retry = client.post(
        "/api/research-graphs/factor-research/versions/2/activation",
        json={
            "approval_ref": (
                "auth-conversation-event:test-orchestrated-activation-retry"
            ),
        },
    )

    assert retry.status_code == 201
    retry_receipt = retry.get_json()["activation"]
    assert retry_receipt["already_active"] is True
    assert retry_receipt["from_version"] == 2
    assert retry_receipt["to_version"] == 2
    assert retry_receipt["rollback_version"] == 1


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
    original_connect = active_pointer.connect_sqlite

    def traced_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(active_pointer, "connect_sqlite", traced_connect)
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
    assert active["lifecycle"] == "draft"
    assert active["active_pointer"]["version"] == 2
    assert len(reads) <= 2
    assert len(writes) == 3
    assert not any(
        "MAX(VERSION)" in statement
        or "INSERT INTO RESEARCH_GRAPH_VERSIONS" in statement
        for statement in normalized
    )
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
        "/api/research-capability-receipts",
    ],
)
def test_obsolete_graph_posts_are_absent(
    client,
    path,
) -> None:
    response = client.post(path, json={})

    assert response.status_code == 404


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
        match="explicit offline cutover",
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
    original_connect = graph_versions.connect_sqlite

    def traced_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(graph_versions, "connect_sqlite", traced_connect)

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
        duplicate_tables = {
            str(row["name"])
            for row in connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name IN (
                    'research_graph_node_resolutions',
                    'research_capability_receipts'
                )
                """
            ).fetchall()
        }
    assert duplicate_tables == set()


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
    original_connect = graph_versions.connect_sqlite

    def traced_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(graph_versions, "connect_sqlite", traced_connect)
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
        for key in graph_versions._GRAPH_CACHE
    )


def test_active_pointer_read_is_two_selects_cold_and_one_warm(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    _active_instance(workspace_id="pointer-read-cache")
    graph_versions.clear_graph_cache_for_current_db()
    statements: list[str] = []
    original_connect = active_pointer.connect_sqlite

    def traced_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(active_pointer, "connect_sqlite", traced_connect)
    cold = research_graphs.load_active_graph(graph_id="factor-research")
    cold_statements = list(statements)
    statements.clear()
    warm = research_graphs.load_active_graph(graph_id="factor-research")

    assert cold["content_hash"] == warm["content_hash"]
    assert sum(
        statement.lstrip().upper().startswith("SELECT ")
        for statement in cold_statements
    ) == 2
    assert sum(
        statement.lstrip().upper().startswith("SELECT ")
        for statement in statements
    ) == 1
    assert not any(
        statement.lstrip().upper().startswith(
            ("INSERT ", "UPDATE ", "DELETE ", "REPLACE ")
        )
        for statement in cold_statements + statements
    )


def test_activation_requires_replay_shadow_capability_and_job_isolation(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    research_graphs.register_graph(_draft_graph(), actor="curator-agent")
    proposal, _ = _approve_proposal()
    with pytest.raises(
        ValueError,
        match="client validation conclusions are not accepted",
    ):
        research_graphs.record_validation(
            graph_id="factor-research",
            version=2,
            proposal_id=proposal["proposal_id"],
            actor="alice",
            evidence={
                **_server_validation_evidence(),
                "shadow_passed": False,
            },
        )


def test_validation_derives_token_regression_as_nonblocking_telemetry(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    research_graphs.register_graph(_draft_graph(), actor="curator-agent")
    proposal, _ = _approve_proposal()

    with pytest.raises(
        ValueError,
        match="client validation conclusions are not accepted",
    ):
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
    validation = research_graphs.record_validation(
        graph_id="factor-research",
        version=2,
        proposal_id=proposal["proposal_id"],
        actor="alice",
        evidence=_server_validation_evidence(
            graph_tokens=120,
            baseline_tokens=100,
        ),
    )
    metrics = validation["evidence"]["token_metrics"]
    assert metrics["shadow_graph_total_tokens"] == 120
    assert metrics["shadow_baseline_total_tokens"] == 100


def test_validation_records_unverified_usage_without_blocking_activation(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    research_graphs.register_graph(_draft_graph(), actor="curator-agent")
    proposal, _ = _approve_proposal()

    validation = research_graphs.record_validation(
        graph_id="factor-research",
        version=2,
        proposal_id=proposal["proposal_id"],
        actor="alice",
        evidence=_server_validation_evidence(
            fallback_graph_usage=True,
        ),
    )

    metrics = validation["evidence"]["token_metrics"]
    assert metrics["provider_actual_token_comparison"] is False
    assert metrics["token_authority"] == "mixed_or_fallback"


def test_validation_records_extra_shadow_usage_without_blocking_activation(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    research_graphs.register_graph(_draft_graph(), actor="curator-agent")
    proposal, _ = _approve_proposal()

    validation = research_graphs.record_validation(
        graph_id="factor-research",
        version=2,
        proposal_id=proposal["proposal_id"],
        actor="alice",
        evidence=_server_validation_evidence(
            extra_shadow_usage=True,
        ),
    )

    metrics = validation["evidence"]["token_metrics"]
    assert metrics["provider_actual_token_comparison"] is False
    assert metrics["token_authority"] == "mixed_or_fallback"


@pytest.mark.parametrize(
    ("evidence_kwargs", "message"),
    [
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


@pytest.mark.parametrize(
    "evidence_kwargs",
    [
        {"graph_tokens": 0},
        {"baseline_tokens": 0},
    ],
)
def test_validation_records_missing_token_measurements_without_blocking(
    tmp_path,
    monkeypatch,
    evidence_kwargs,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    research_graphs.register_graph(_draft_graph(), actor="curator-agent")
    proposal, _ = _approve_proposal()

    validation = research_graphs.record_validation(
        graph_id="factor-research",
        version=2,
        proposal_id=proposal["proposal_id"],
        actor="alice",
        evidence=_server_validation_evidence(**evidence_kwargs),
    )

    metrics = validation["evidence"]["token_metrics"]
    assert metrics["provider_actual_token_comparison"] is False
    assert (
        metrics["shadow_graph_total_tokens"] == 0
        or metrics["shadow_baseline_total_tokens"] == 0
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
    assert active["lifecycle"] == "draft"
    assert active["is_active"] is True


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
    first_validation_evidence = _server_validation_evidence()
    research_graphs.record_validation(
        graph_id="factor-research",
        version=2,
        proposal_id=proposal["proposal_id"],
        actor="alice",
        evidence=first_validation_evidence,
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
    second_draft["parent_version"] = 2
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
    rollback_reason = "shadow regression after activation"
    rollback_authorization = _authorize_rollback(
        from_version=4,
        target_version=2,
        reason=rollback_reason,
        validation_evidence=first_validation_evidence,
    )
    statements: list[str] = []
    original_connect = active_pointer.connect_sqlite

    def traced_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(active_pointer, "connect_sqlite", traced_connect)
    rollback = research_graphs.rollback_active_graph(
        graph_id="factor-research",
        target_version=first_active["version"],
        actor="alice",
        reason=rollback_reason,
        human_authorization_id=rollback_authorization["authorization_id"],
    )
    normalized = [statement.lstrip().upper() for statement in statements]
    assert sum(
        statement.startswith("SELECT ") for statement in normalized
    ) <= 3
    assert sum(
        statement.startswith(("INSERT ", "UPDATE ", "DELETE ", "REPLACE "))
        for statement in normalized
    ) == 2
    assert sum(
        statement.startswith("BEGIN IMMEDIATE")
        for statement in normalized
    ) == 1
    assert not any(
        "RESEARCH_GRAPH_ROLLBACKS" in statement
        or "INSERT INTO RESEARCH_GRAPH_VERSIONS" in statement
        or "MAX(VERSION)" in statement
        for statement in normalized
    )

    assert second_active["version"] == 4
    assert rollback["from_version"] == 4
    assert rollback["to_version"] == 2
    assert research_graphs.load_active_graph(
        graph_id="factor-research"
    )["version"] == 2
    with research_graphs.connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        assert conn.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type='table' AND name='research_graph_rollbacks'
            """
        ).fetchone() is None
        conn.execute(
            """
            UPDATE active_research_graphs
            SET version=4, activated_by='alice', activated_at=99
            WHERE graph_id='factor-research'
            """
        )
    with pytest.raises(
        research_graphs.GraphActivationBlocked,
        match="already consumed",
    ):
        research_graphs.rollback_active_graph(
            graph_id="factor-research",
            target_version=2,
            actor="alice",
            reason=rollback_reason,
            human_authorization_id=rollback_authorization[
                "authorization_id"
            ],
        )
    cas_reason = rollback_reason + " after concurrent update"
    fresh_authorization = _authorize_rollback(
        from_version=4,
        target_version=2,
        reason=cas_reason,
        validation_evidence=first_validation_evidence,
    )
    consume_rollback = (
        active_pointer.pointer_gate.consume_rollback
    )

    def consume_then_race(conn, **kwargs):
        result = consume_rollback(conn, **kwargs)
        conn.execute(
            """
            UPDATE active_research_graphs SET version=999
            WHERE graph_id='factor-research'
            """
        )
        return result

    monkeypatch.setattr(
        active_pointer.pointer_gate,
        "consume_rollback",
        consume_then_race,
    )
    with pytest.raises(
        research_graphs.GraphActivationBlocked,
        match="changed during rollback",
    ):
        research_graphs.rollback_active_graph(
            graph_id="factor-research",
            target_version=2,
            actor="alice",
            reason=cas_reason,
            human_authorization_id=fresh_authorization["authorization_id"],
        )
    with research_graphs.connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        pointer = conn.execute(
            """
            SELECT version FROM active_research_graphs
            WHERE graph_id='factor-research'
            """
        ).fetchone()
        gate = conn.execute(
            """
            SELECT status FROM research_maintenance_cases
            WHERE case_id=?
            """,
            (fresh_authorization["authorization_id"],),
        ).fetchone()
    assert int(pointer["version"]) == 4
    assert gate["status"] == "blocked"


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
    assert activated.get_json()["graph"]["lifecycle"] == "draft"
    assert activated.get_json()["graph"]["active_pointer"]["version"] == 2

    resolution = _capability_resolution(
        node_id="hypothesis",
        product_group="equities",
        capability_ids=["research-hypothesis.preregister"],
    )
    instance = research_graphs.create_graph_instance(
        graph_id="factor-research",
        owner="alice",
        product_group="equities",
        workspace_id="http-workspace",
        capability_resolution=resolution,
    )
    branch_id = instance["branches"][0]["branch_id"]
    node_response = client.get(
        f"/api/research-graph-instances/{instance['instance_id']}"
        f"/branches/{branch_id}/node"
    )
    assert node_response.status_code == 200
    node = node_response.get_json()["node"]
    assert "capabilities" in node
    assert "candidate_edges" in node
    assert "next_actions" in node
    history = client.get("/api/research-graphs/factor-research/versions")
    assert [item["lifecycle"] for item in history.get_json()["versions"]] == [
        "draft",
    ]


def test_instance_creation_writes_only_instance_and_branch(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    _active_instance(workspace_id="create-owner-setup")
    resolution = _capability_resolution(
        node_id="hypothesis",
        product_group="equities",
        capability_ids=["research-hypothesis.preregister"],
    )
    statements: list[str] = []
    original_connect = branch_runtime.connect_sqlite

    def traced_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(branch_runtime, "connect_sqlite", traced_connect)
    research_graphs.create_graph_instance(
        graph_id="factor-research",
        owner="alice",
        product_group="equities",
        workspace_id="create-owner-measured",
        capability_resolution=resolution,
    )

    inserts = [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith("INSERT ")
    ]
    assert len(inserts) == 3
    assert any(
        "INTO RESEARCH_GRAPH_INSTANCES" in statement.upper()
        for statement in inserts
    )
    assert any(
        "INTO RESEARCH_GRAPH_BRANCHES" in statement.upper()
        for statement in inserts
    )
    assert any(
        "INTO RESEARCH_WORK_PACKAGES" in statement.upper()
        for statement in inserts
    )
    assert not any(
        table.upper() in statement.upper()
        for table in (
            "research_graph_node_resolutions",
            "research_capability_receipts",
        )
        for statement in statements
    )

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
        capability_resolution=_capability_resolution(
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
        "required_research_evidence": [],
        "required_transition_facts": [],
            "blockers": [],
            "review_requirement": "none",
            "target_required_capability_ids": [],
        }]
    assert next_packet["recommended_edge_ids"] == []
    assert next_packet["requires_agent_judgment"] is False
    assert next_packet["next_bytes"] == len(orjson.dumps(next_packet))
    assert next_packet["next_bytes"] <= 6000
    assert "required_capabilities" not in next_packet
    assert next_packet["capabilities"] == [{
        "capability_id": "research-hypothesis.preregister",
        "capability_description": (
            "Test contract for research-hypothesis.preregister."
        ),
        "descriptor_hash": graph["capability_descriptors"][
            "research-hypothesis.preregister"
        ]["descriptor_hash"],
        "status": "bound",
    }]
    assert next_packet["current_obligations"] == []
    assert next_packet["candidate_trial_frontier"] == {
        "current_trial_plan_hash": None,
        "trial_stage": None,
        "candidate_plan_refs": [],
        "unassessed_obligation_count": 0,
    }

    transition_statements: list[str] = []
    original_connect = branch_transition.connect_sqlite

    def traced_transition_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(transition_statements.append)
        return connection

    monkeypatch.setattr(
        branch_transition,
        "connect_sqlite",
        traced_transition_connect,
    )
    initial_cycle = validate_research_cycle_checkpoint({
        "schema_version": 1,
        "contract_hash": "1" * 64,
        "trial_plan_hash": "",
        "methodology_hash": "2" * 64,
        "claims": [{
            "schema_version": 1,
            "claim_id": "claim-branch",
            "contract_hash": "1" * 64,
            "claim_ref": "factor-claim:branch",
            "claim_type": "bounded_predictive_relationship",
            "scope": {"product_group": "china_futures"},
            "evidence_state": "unknown",
            "evidence_refs": [],
        }],
        "obligations": [{
            "schema_version": 1,
            "obligation_id": "obligation-roll-window",
            "contract_hash": "1" * 64,
            "claim_ids": ["claim-branch"],
            "obligation_kind": "roll_window_artifact",
            "epistemic_question": "Does roll proximity explain the signal?",
            "scope": {"product_group": "china_futures"},
            "discharge_criterion": {"method": "window exclusion"},
            "status": "open",
            "materiality": "decision_blocking",
            "methodology_hash": "2" * 64,
            "created_event_ref": "trace:first-principles",
        }],
        "pending_adjudications": [],
        "pending_closure": None,
    })
    transitioned = research_graphs.advance_graph_branch(
        instance_id=instance["instance_id"],
        branch_id=first["branch_id"],
        owner="alice",
        edge_id="hypothesis__resolution",
        evidence={
            "hypothesis_frozen": True,
            "evidence_envelope": {
                "schema_version": 2,
                "envelope_id": "evidence-canonical",
                "evidence_kind": "hypothesis_semantics",
                "source_refs": ["analysis:canonical"],
                "identity_refs": {
                    "contract_hash": "1" * 64,
                    "methodology_hash": "2" * 64,
                },
                "metric_refs": [],
                "artifact_refs": [],
                "hypotheses_tested": 1,
                "stop_condition": None,
                "limitations": [],
                "conflicts": [],
            },
            "research_cycle": {
                "schema_version": 1,
                "parent_trace_ref": "",
                "initial_checkpoint": initial_cycle,
                "expected_base_hash": initial_cycle["projection_hash"],
                "events": [],
            },
        },
    )
    monkeypatch.setattr(
        branch_transition,
        "connect_sqlite",
        original_connect,
    )
    transition_selects = [
        statement for statement in transition_statements
        if statement.lstrip().upper().startswith("SELECT ")
    ]
    assert len(transition_selects) == 1
    assert sum(
        statement.lstrip().upper().startswith("BEGIN IMMEDIATE")
        for statement in transition_statements
    ) == 1
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
    carrier = transitioned["report_checkpoint"]
    assert carrier["checkpoint_ref"].startswith("trace:")
    assert carrier["work_package_ref"] == (
        f"work-package:{instance['instance_id']}"
    )
    assert carrier["branch_ref"] == (
        "graph-branch:"
        f"{instance['instance_id']}:{first['branch_id']}"
    )
    assert carrier["decision_contract_hash"] == "1" * 64
    assert carrier["methodology_hash"] == "2" * 64
    assert carrier["latest_transition"]["edge_ref"] == (
        "graph-edge:hypothesis__resolution"
    )
    assert carrier["schema_version"] == 2
    assert carrier["report_lineage"] == {
        "status": "root",
        "predecessor_checkpoint_ref": "",
    }
    serialized_carrier = orjson.dumps(carrier)
    assert b"source_code" not in serialized_carrier
    assert b"stdout" not in serialized_carrier
    with research_graphs.connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        trace = conn.execute(
            """
            SELECT evidence_json FROM research_graph_trace
            WHERE instance_id=? AND branch_id=?
            ORDER BY created_at DESC LIMIT 1
            """,
            (
                transitioned["instance_id"],
                transitioned["branch_id"],
            ),
        ).fetchone()
    envelope = orjson.loads(trace["evidence_json"])["evidence_envelope"]
    persisted_lineage = orjson.loads(trace["evidence_json"])[
        "report_lineage"
    ]
    assert persisted_lineage == carrier["report_lineage"]
    assert len(envelope["envelope_hash"]) == 64
    assert "decision" not in envelope
    before_oversized = research_graphs.load_graph_branch(
        instance_id=instance["instance_id"],
        branch_id=first["branch_id"],
        owner="alice",
    )
    with research_graphs.connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        trace_count_before = conn.execute(
            """
            SELECT COUNT(*) AS count FROM research_graph_trace
            WHERE instance_id=? AND branch_id=?
            """,
            (instance["instance_id"], first["branch_id"]),
        ).fetchone()["count"]
    cycle_context = research_graphs.build_graph_branch_context(
        instance_id=instance["instance_id"],
        branch_id=first["branch_id"],
        owner="alice",
    )
    cycle_next = research_graphs.build_graph_branch_next(
        instance_id=instance["instance_id"],
        branch_id=first["branch_id"],
        owner="alice",
    )
    assert cycle_next["current_obligations"][0][
        "obligation_id"
    ] == "obligation-roll-window"
    assert cycle_next["candidate_trial_frontier"][
        "unassessed_obligation_count"
    ] == 1
    assert cycle_next["candidate_edges"][0][
        "required_research_evidence"
    ] == []
    assert cycle_next["candidate_edges"][0][
        "required_transition_facts"
    ] == ["missing capability id"]
    assert "required_evidence" not in cycle_next["candidate_edges"][0]
    assert cycle_context["history_cursor"] in cycle_next["changed_refs"]
    with pytest.raises(ValueError, match="base projection hash is stale"):
        research_graphs.advance_graph_branch(
            instance_id=instance["instance_id"],
            branch_id=first["branch_id"],
            owner="alice",
            edge_id="resolution__gap",
            evidence={
                "mandatory_binding_missing": True,
                "evidence_refs": ["artifact:stale-cycle"],
                "research_cycle": {
                    "schema_version": 1,
                    "parent_trace_ref": cycle_context["history_cursor"],
                    "expected_base_hash": "9" * 64,
                    "events": [],
                },
            },
        )
    with research_graphs.connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        trace_count_after_stale = conn.execute(
            """
            SELECT COUNT(*) AS count FROM research_graph_trace
            WHERE instance_id=? AND branch_id=?
            """,
            (instance["instance_id"], first["branch_id"]),
        ).fetchone()["count"]
    assert trace_count_after_stale == trace_count_before
    assert research_graphs.load_graph_branch(
        instance_id=instance["instance_id"],
        branch_id=first["branch_id"],
        owner="alice",
    ) == before_oversized
    inherited = research_graphs.fork_graph_branch(
        instance_id=instance["instance_id"],
        source_branch_id=first["branch_id"],
        owner="alice",
        label="checkpoint inheritance",
    )
    inherited_context = research_graphs.build_graph_branch_context(
        instance_id=instance["instance_id"],
        branch_id=inherited["branch_id"],
        owner="alice",
    )
    assert inherited_context["research_cycle"]["projection_hash"] == (
        cycle_context["research_cycle"]["projection_hash"]
    )
    assert inherited_context["history_cursor"] != cycle_context["history_cursor"]
    with research_graphs.connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        inherited_trace = conn.execute(
            """
            SELECT edge_id FROM research_graph_trace
            WHERE trace_id=?
            """,
            (inherited_context["history_cursor"].removeprefix("trace:"),),
        ).fetchone()
        inherited_row = load_instance_branch_row(
            conn,
            instance_id=instance["instance_id"],
            branch_id=inherited["branch_id"],
            owner="alice",
        )
    assert inherited_trace["edge_id"] == "__branch_fork__"
    assert inherited_row is not None
    assert replay_shadow_trace(
        graph=graph,
        runtime=inherited_row,
    )["research_cycle_status"] == "current"
    monkeypatch.setattr(
        branch_transition,
        "connect_sqlite",
        lambda *_args, **_kwargs: pytest.fail(
            "oversized evidence reached the database"
        ),
    )
    with pytest.raises(
        ValueError,
        match=(
            "transition evidence transport exceeds "
            f"{MAX_AGENT_TRANSITION_BYTES} bytes"
        ),
    ):
        research_graphs.advance_graph_branch(
            instance_id=instance["instance_id"],
            branch_id=first["branch_id"],
            owner="alice",
            edge_id="resolution__gap",
            evidence={
                "mandatory_binding_missing": True,
                "evidence_refs": ["artifact:oversized"],
                "research_note": "x" * MAX_AGENT_TRANSITION_BYTES,
            },
        )
    monkeypatch.setattr(
        branch_transition,
        "connect_sqlite",
        original_connect,
    )
    assert research_graphs.load_graph_branch(
        instance_id=instance["instance_id"],
        branch_id=first["branch_id"],
        owner="alice",
    ) == before_oversized
    with research_graphs.connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        trace_count_after = conn.execute(
            """
            SELECT COUNT(*) AS count FROM research_graph_trace
            WHERE instance_id=? AND branch_id=?
            """,
            (instance["instance_id"], first["branch_id"]),
        ).fetchone()["count"]
    assert trace_count_after == trace_count_before

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
    assert paused["report_checkpoint"]["report_lineage"] == {
        "status": "linked",
        "predecessor_checkpoint_ref": carrier["checkpoint_ref"],
    }
    assert untouched["status"] == "running"
    assert untouched["current_node"] == "hypothesis"

    with research_graphs.connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.executemany(
            """
            INSERT INTO research_graph_trace (
                trace_id, instance_id, branch_id, edge_id, from_node, to_node,
                evidence_json, telemetry_json, actor, created_at
            ) VALUES (?, ?, ?, 'historical-only', 'x', 'x', '{}', '{}',
                      'history-fixture', ?)
            """,
            [
                (
                    f"historical-trace-{index}",
                    instance["instance_id"],
                    first["branch_id"],
                    float(index),
                )
                for index in range(250)
            ],
        )
    statements: list[str] = []
    original_connect = branch_context.connect_sqlite

    def traced_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(branch_context, "connect_sqlite", traced_connect)
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
            "trial_stage",
            "research_cycle",
        "open_gaps",
            "skill_policy",
                "review_policy",
                "report_container",
                "context_bytes",
        }
    assert context["graph"] == "factor-research@v2"
    assert "nodes" not in context
    assert "token_telemetry" not in context
    assert "review_gate" not in context
    assert context["review_policy"]["L1"] == "deterministic_only"
    assert context["evidence_refs"] == [
        f"artifact:capability-gap:{index}"
        for index in range(4, 10)
    ]
    assert context["omitted_evidence_count"] == 4
    assert context["history_cursor"].startswith("trace:")
    assert context["research_cycle"]["protocol_status"] == "current"
    assert context["research_cycle"]["claim_states"] == [{
        "claim_id": "claim-branch",
        "claim_ref": "factor-claim:branch",
        "claim_type": "bounded_predictive_relationship",
        "scope": {"product_group": "china_futures"},
        "evidence_state": "unknown",
        "detail_ref": "research-cycle-object:claim:claim-branch",
    }]
    assert "LEFT JOIN RESEARCH_GRAPH_TRACE" in " ".join(
        statement.upper() for statement in statements
    )
    assert not any(
        "FROM RESEARCH_GRAPH_TRACE" in statement.upper()
        for statement in statements
    )
    selects = [
        statement for statement in statements
        if statement.lstrip().upper().startswith("SELECT ")
    ]
    assert len(selects) == 1
    assert not any(
        "RESEARCH_GRAPH_VERSIONS" in statement.upper()
        for statement in selects
    )
    statements.clear()
    next_packet = research_graphs.build_graph_branch_next(
        instance_id=instance["instance_id"],
        branch_id=first["branch_id"],
        owner="alice",
    )
    next_selects = [
        statement for statement in statements
        if statement.lstrip().upper().startswith("SELECT ")
    ]
    assert len(next_selects) == 1
    assert not any(
        statement.lstrip().upper().startswith(
            ("INSERT ", "UPDATE ", "DELETE ")
        )
        for statement in statements
    )
    assert next_packet["next_bytes"] <= 4000

    monkeypatch.setattr(branch_context, "connect_sqlite", original_connect)


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
        capability_resolution=_capability_resolution(
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
    target_resolution = _capability_resolution(
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
            # The Agent delta remains below 6000 bytes.  The independently
            # bounded deterministic resolution must not make it fail.
            "research_note": "x" * 5_300,
            "target_capability_resolution": target_resolution,
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
    assert "token_telemetry" not in context
    assert context["branch"]["status"] == "running"
    assert "review_gate" not in context
    assert context["skill_policy"]["agent_action"] == (
        "reuse_matching_runtime_skill_else_load_after_trigger_and_approval"
    )
    with research_graphs.connect_sqlite(Settings.CACHE_DB_PATH) as connection:
        before = connection.execute(
            """
            SELECT updated_at, current_capability_resolution_json
            FROM research_graph_branches
            WHERE instance_id=? AND branch_id=? AND current_node=?
            """,
            (
                instance["instance_id"],
                branch["branch_id"],
                "validation",
            ),
        ).fetchone()
        resolution = orjson.loads(
            before["current_capability_resolution_json"]
        )
        _, unchanged_write_count = (
            research_graphs._store_current_branch_resolution(
            connection,
            instance_id=instance["instance_id"],
            branch_id=branch["branch_id"],
            node_id="validation",
            resolution=resolution,
        )
        )
        after = connection.execute(
            """
            SELECT updated_at
            FROM research_graph_branches
            WHERE instance_id=? AND branch_id=? AND current_node=?
            """,
            (
                instance["instance_id"],
                branch["branch_id"],
                "validation",
            ),
        ).fetchone()
    assert unchanged_write_count == 0
    assert after["updated_at"] == before["updated_at"]
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
        invocation_id=granted["invocation_id"],
    )
    budget = store.load_current_budget_period(
        owner_user_id="alice",
        agent_id="hard-limit",
    )
    assert released["released_tokens"] == 80
    assert budget["available_tokens"] == 100


def test_undetermined_condition_is_compact_and_keeps_failure_route_open(
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
    graph["nodes"].extend([
        {
            "node_id": "data_contract",
            "kind": "validation",
            "purpose": "inspect exact data availability",
            "enforcement": "deterministic",
            "required_capabilities": [],
            "entry_evidence": [],
            "exit_evidence": [],
        },
        {
            "node_id": "capability_gap",
            "kind": "capability_gap",
            "purpose": "resolve an unavailable or uncertain capability",
            "enforcement": "deterministic",
            "required_capabilities": [],
            "entry_evidence": [],
            "exit_evidence": [],
        },
    ])
    graph["edges"] = [
        {
            "edge_id": "hypothesis__data_contract",
            "from_node": "hypothesis",
            "to_node": "data_contract",
            "edge_type": "conditional",
            "guard": {"hypothesis_frozen": True},
            "required_evidence": [],
            "counterexamples": [],
            "risk_level": "L1",
        },
        {
            "edge_id": "hypothesis__capability_gap",
            "from_node": "hypothesis",
            "to_node": "capability_gap",
            "edge_type": "failure",
            "guard": {"mandatory_binding_missing": True},
            "required_evidence": [],
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
        grill_evidence=[{"question": "conditional?", "answer": "bounded"}],
        grill_ref="grill-with-docs:test-condition-resolution",
    )
    active = _activate()
    instance = research_graphs.create_graph_instance(
        graph_id="factor-research",
        owner="alice",
        product_group="equities",
        workspace_id="workspace-conditional",
        capability_resolution=_capability_resolution(
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
    next_packet = research_graphs.build_graph_branch_next(
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
    assert next_packet["unresolved_capability_conditions"] == [{
        "capability_id": "factor-combination.multi-factor",
        "explanation": "factor.is_multi is unavailable",
    }]
    next_edges = {
        item["edge_id"]: item for item in next_packet["candidate_edges"]
    }
    assert next_edges["hypothesis__data_contract"]["readiness"] == "blocked"
    assert next_edges["hypothesis__data_contract"]["blockers"] == [{
        "code": "semantic_conditions_undetermined",
        "capability_ids": ["factor-combination.multi-factor"],
    }]
    assert next_edges["hypothesis__capability_gap"]["readiness"] == (
        "requires_evidence"
    )
    assert next_edges["hypothesis__capability_gap"]["blockers"] == []
    assert next_packet["next_bytes"] == len(orjson.dumps(next_packet))
    assert next_packet["next_bytes"] <= 6000
    assert context["context_bytes"] == len(orjson.dumps(context))
    assert context["context_bytes"] <= 6000
    assert active["version"] == 2


def test_triggered_conditional_gap_is_local_and_blocks_next(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    graph = _draft_graph()
    node = graph["nodes"][0]
    capability_id = "market-microstructure.intraday-diagnose"
    node["conditional_capabilities"] = [{
        "capability_id": capability_id,
        "predicate": {"field": "signal.frequency", "in": ["MIN1"]},
        "explanation": "Use only for intraday signals.",
    }]
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
        grill_ref="grill-with-docs:test-triggered-gap",
    )
    _activate()
    resolution = _capability_resolution(
        node_id="hypothesis",
        product_group="equities",
        capability_ids=["research-hypothesis.preregister"],
    )
    resolution["triggered_conditional_gaps"] = [{
        "capability_id": capability_id,
        **graph["capability_descriptors"][capability_id],
        "reason": "no approved implementation supports MIN1",
    }]
    tampered_resolution = deepcopy(resolution)
    tampered_resolution["triggered_conditional_gaps"][0][
        "descriptor_hash"
    ] = "0" * 64
    with pytest.raises(ValueError, match="capability descriptor mismatch"):
        research_graphs.create_graph_instance(
            graph_id="factor-research",
            owner="alice",
            product_group="equities",
            workspace_id="workspace-triggered-gap",
            capability_resolution=tampered_resolution,
        )
    instance = research_graphs.create_graph_instance(
        graph_id="factor-research",
        owner="alice",
        product_group="equities",
        workspace_id="workspace-triggered-gap",
        capability_resolution=resolution,
    )
    branch_id = instance["branches"][0]["branch_id"]

    context = research_graphs.build_graph_branch_context(
        instance_id=instance["instance_id"],
        branch_id=branch_id,
        owner="alice",
    )
    next_packet = research_graphs.build_graph_branch_next(
        instance_id=instance["instance_id"],
        branch_id=branch_id,
        owner="alice",
    )

    assert [
        item["capability_id"] for item in context["open_gaps"]
    ] == [capability_id]
    assert all(
        edge["readiness"] == "blocked"
        for edge in next_packet["candidate_edges"]
        if edge["edge_type"] != "failure"
    )
