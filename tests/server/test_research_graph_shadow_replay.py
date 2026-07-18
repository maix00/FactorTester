"""Server-owned shadow replay and non-mutation acceptance tests."""

from __future__ import annotations

import uuid

import pytest

import settings as Settings
from server.jobs.models import JobRecord
from server.jobs.repository import JobRepository
from server.jobs.states import JobStatus
from server.services import research_graphs, research_runs
from tests.server.test_research_graphs import (
    _approve_proposal,
    _capability_resolution,
    _draft_graph,
    _hash,
    _initialize_graph_db,
    _server_validation_evidence,
)


def _graph_with_transition() -> dict:
    graph = _draft_graph()
    graph["entry_node"] = "hypothesis"
    graph["nodes"].append({
        "node_id": "validation",
        "kind": "research",
        "purpose": "validate factor",
        "enforcement": "deterministic",
        "required_capabilities": [],
        "entry_evidence": [],
        "exit_evidence": [],
    })
    graph["edges"] = [{
        "edge_id": "hypothesis__validation",
        "from_node": "hypothesis",
        "to_node": "validation",
        "edge_type": "recommended",
        "guard": {"hypothesis_frozen": True},
        "required_evidence": ["hypothesis"],
        "counterexamples": [],
        "risk_level": "L1",
    }]
    graph["content_hash"] = _hash(graph)
    return graph


def _advance_shadow(evidence: dict) -> tuple[str, str]:
    refs = evidence["shadow_comparison_refs"]
    instance_id = refs["routine_instance_id"]
    branch_id = refs["routine_branch_id"]
    research_graphs.advance_graph_branch(
        instance_id=instance_id,
        branch_id=branch_id,
        owner="alice",
        edge_id="hypothesis__validation",
        evidence={
            "hypothesis_frozen": True,
            "evidence_refs": ["artifact:hypothesis"],
            "agent_invocation_ids": [],
            "target_capability_resolution": _capability_resolution(
                node_id="validation",
                product_group="equities",
                capability_ids=[],
                graph_version=2,
            ),
        },
    )
    return instance_id, branch_id


def _comparison_job(
    *,
    run_id: str,
    job_id: str,
    kind: str = "backtest",
) -> None:
    run = research_runs.load_run(run_id=run_id, owner="alice")
    assert run is not None
    repository = JobRepository()
    repository.create(JobRecord(
        job_id=job_id,
        run_id=run_id,
        owner="alice",
        workspace_id=run["workspace_id"],
        kind=kind,
        status=JobStatus.SUBMITTED,
        source_revision="shadow-test-revision",
        runner_path="test:shadow",
        job_spec={
            "run_id": run_id,
            "workspace_id": run["workspace_id"],
            "run_spec": run["run_spec"],
        },
        run_spec_hash=run["run_spec_hash"],
    ))
    repository.record_artifact(
        job_id=job_id,
        name="metrics",
        relative_path=f"{job_id}/metrics.json",
        content_type="application/json",
        content_hash="a" * 64,
        size_bytes=12,
    )
    repository.transition(job_id, JobStatus.PLANNING)
    repository.set_execution_plan(
        job_id,
        plan={"runner": "test:shadow", "steps": ["compute"]},
        notices=[],
        requires_confirmation=False,
    )
    repository.transition(job_id, JobStatus.RUNNING, worker_pid=123)
    repository.transition(
        job_id,
        JobStatus.SUCCEEDED,
        worker_exitcode=0,
        result_summary={"sharpe": 1.0, "observations": 100},
    )


def _canonical_execution_rows() -> tuple[list[tuple], list[tuple], list[tuple]]:
    with research_graphs.connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        runs = [
            tuple(row)
            for row in conn.execute(
                "SELECT * FROM research_runs ORDER BY run_id"
            ).fetchall()
        ]
        jobs = [
            tuple(row)
            for row in conn.execute(
                "SELECT * FROM research_jobs ORDER BY job_id"
            ).fetchall()
        ]
        artifacts = [
            tuple(row)
            for row in conn.execute(
                """
                SELECT * FROM research_job_artifacts
                ORDER BY job_id, name
                """
            ).fetchall()
        ]
    return runs, jobs, artifacts


def test_validation_replays_trace_and_never_mutates_execution_history(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    research_graphs.register_graph(
        _graph_with_transition(),
        actor="curator-agent",
    )
    proposal, _ = _approve_proposal()
    evidence = _server_validation_evidence()
    instance_id, _ = _advance_shadow(evidence)
    with research_graphs.connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        graph_run_id = str(conn.execute(
            """
            SELECT shadow_run_id FROM research_graph_instances
            WHERE instance_id=?
            """,
            (instance_id,),
        ).fetchone()["shadow_run_id"])
    baseline_run_id = evidence[
        "shadow_comparison_refs"
    ]["baseline_run_id"]
    _comparison_job(run_id=graph_run_id, job_id=f"graph-{uuid.uuid4().hex}")
    _comparison_job(
        run_id=baseline_run_id,
        job_id=f"baseline-{uuid.uuid4().hex}",
    )
    before = _canonical_execution_rows()

    validation = research_graphs.record_validation(
        graph_id="factor-research",
        version=2,
        proposal_id=proposal["proposal_id"],
        actor="alice",
        evidence=evidence,
    )

    assert validation["evidence"]["evidence_authority"] == "server_derived"
    replay = validation["evidence"]["replay_summary"]
    assert replay["passed"] is True
    assert replay["transition_count"] == 1
    assert validation["evidence"]["shadow_summary"]["equivalent"] is True
    assert _canonical_execution_rows() == before


def test_tampered_trace_cannot_create_an_accepted_validation(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    research_graphs.register_graph(
        _graph_with_transition(),
        actor="curator-agent",
    )
    proposal, _ = _approve_proposal()
    evidence = _server_validation_evidence()
    instance_id, branch_id = _advance_shadow(evidence)
    with research_graphs.connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        before_ref = str(conn.execute(
            """
            SELECT latest_result_ref FROM research_maintenance_cases
            WHERE case_id=?
            """,
            (proposal["proposal_id"],),
        ).fetchone()["latest_result_ref"])
        conn.execute(
            """
            UPDATE research_graph_trace SET to_node='tampered'
            WHERE instance_id=? AND branch_id=?
            """,
            (instance_id, branch_id),
        )

    with pytest.raises(ValueError, match="replay_passed"):
        research_graphs.record_validation(
            graph_id="factor-research",
            version=2,
            proposal_id=proposal["proposal_id"],
            actor="alice",
            evidence=evidence,
        )

    with research_graphs.connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        after_ref = str(conn.execute(
            """
            SELECT latest_result_ref FROM research_maintenance_cases
            WHERE case_id=?
            """,
            (proposal["proposal_id"],),
        ).fetchone()["latest_result_ref"])
    assert after_ref == before_ref


def test_shadow_comparison_rejects_different_job_semantics(
    tmp_path,
    monkeypatch,
) -> None:
    _initialize_graph_db(tmp_path, monkeypatch)
    research_graphs.register_graph(
        _graph_with_transition(),
        actor="curator-agent",
    )
    proposal, _ = _approve_proposal()
    evidence = _server_validation_evidence()
    instance_id, _ = _advance_shadow(evidence)
    with research_graphs.connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        graph_run_id = str(conn.execute(
            """
            SELECT shadow_run_id FROM research_graph_instances
            WHERE instance_id=?
            """,
            (instance_id,),
        ).fetchone()["shadow_run_id"])
    baseline_run_id = evidence[
        "shadow_comparison_refs"
    ]["baseline_run_id"]
    _comparison_job(
        run_id=graph_run_id,
        job_id=f"graph-{uuid.uuid4().hex}",
        kind="backtest",
    )
    _comparison_job(
        run_id=baseline_run_id,
        job_id=f"baseline-{uuid.uuid4().hex}",
        kind="ic",
    )

    with pytest.raises(ValueError, match="shadow_passed"):
        research_graphs.record_validation(
            graph_id="factor-research",
            version=2,
            proposal_id=proposal["proposal_id"],
            actor="alice",
            evidence=evidence,
        )
