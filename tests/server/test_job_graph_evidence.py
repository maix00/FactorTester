"""Server-owned JobAttempt evidence on the backtest transition."""

from __future__ import annotations

import hashlib

import orjson
import pytest

import settings as Settings
from server.jobs.models import JobRecord
from server.jobs.repository import JobRepository
from server.jobs.states import JobStatus
from server.services.research_graph.branch.transition import advance_graph_branch
from server.services.research_graph.research_cycle.replay import (
    validate_research_cycle_checkpoint,
)
from server.services.research_run_schema import ensure_schema
from tests.server.data_contract_fixtures import checkpoint, initialize
from tools.data.sqlite.db import connect_sqlite


PLAN_HASH = "3" * 64
RUN_SPEC = {"prehashed": True}
RUN_SPEC_HASH = hashlib.sha256(
    orjson.dumps(RUN_SPEC, option=orjson.OPT_SORT_KEYS)
).hexdigest()


def _graph() -> dict:
    return {
        "graph_id": "factor-research",
        "version": 1,
        "lifecycle": "active",
        "content_hash": "c" * 64,
        "entry_node": "authoritative_backtest",
        "nodes": [
            {
                "node_id": "authoritative_backtest",
                "kind": "research",
                "required_capabilities": [],
            },
            {
                "node_id": "statistical_robustness",
                "kind": "research",
                "required_capabilities": [],
            },
        ],
        "edges": [{
            "edge_id": "backtest__statistical_robustness",
            "from_node": "authoritative_backtest",
            "to_node": "statistical_robustness",
            "guard": {
                "terminal_job_evidence_retained": True,
                "terminal_job_trusted": True,
                "net_return_series_available": True,
            },
            "required_evidence": [],
            "server_action": "bind_job_attempt",
        }],
    }


def _prepare(path, *, run_branch: str = "branch-1") -> JobRepository:
    initialize(path)
    cycle = checkpoint()
    cycle.pop("projection_hash", None)
    cycle["trial_plan_hash"] = PLAN_HASH
    cycle = validate_research_cycle_checkpoint(cycle)
    with connect_sqlite(path) as conn:
        ensure_schema(conn)
        conn.execute(
            """
            UPDATE research_graph_versions SET graph_json=?
            WHERE graph_id='factor-research' AND version=1
            """,
            (orjson.dumps(_graph()).decode(),),
        )
        conn.execute(
            """
            UPDATE research_graph_branches
            SET current_node='authoritative_backtest',
                current_trial_plan_hash=?
            WHERE branch_id='branch-1'
            """,
            (PLAN_HASH,),
        )
        conn.execute(
            """
            UPDATE research_graph_trace SET evidence_json=?
            WHERE trace_id='trace-bootstrap'
            """,
            (orjson.dumps({
                "research_cycle_checkpoint": cycle,
                "evidence_refs": [],
            }).decode(),),
        )
        conn.execute(
            """
            INSERT INTO research_runs (
                run_id, owner, workspace_id, configuration_id,
                configuration_revision, kind, run_spec_version,
                run_spec_hash, run_spec_json, decision_contract_hash,
                methodology_hash, trial_plan_id, trial_plan_hash,
                trial_plan_version, trial_role, trial_stage, comparison_id,
                graph_instance_id, graph_branch_id, sample_ref, sample_hash,
                created_at
            ) VALUES (
                'run-1', 'alice', 'workspace-1', 'configuration-1',
                1, 'factor_research', 2, ?, '{}', ?, ?, 'plan-1', ?,
                1, 'selection', 'selection', 'main', 'instance-1', ?,
                'selection-sample', ?, 1
            )
            """,
            (
                RUN_SPEC_HASH,
                cycle["contract_hash"],
                cycle["methodology_hash"],
                PLAN_HASH,
                run_branch,
                "5" * 64,
            ),
        )
    repository = JobRepository(path)
    record = JobRecord(
        job_id="job-1",
        run_id="run-1",
        owner="alice",
        workspace_id="workspace-1",
        kind="backtest",
        status=JobStatus.SUBMITTED,
        source_revision="backend-1",
        runner_path="tests.server.long_lived_worker_fakes:cpu_runner",
        job_spec={"run_spec": RUN_SPEC},
        run_spec_hash=RUN_SPEC_HASH,
    )
    repository.create(record)
    repository.transition("job-1", JobStatus.PLANNING)
    repository.set_execution_plan(
        "job-1",
        plan={"runner": record.runner_path, "steps": ["compute"]},
        notices=[],
        requires_confirmation=False,
    )
    repository.transition("job-1", JobStatus.RUNNING)
    repository.record_artifact(
        job_id="job-1",
        name="net_returns",
        relative_path="job-1/net_returns.parquet",
        content_type="application/x-parquet",
        content_hash="6" * 64,
        size_bytes=128,
    )
    repository.transition(
        "job-1",
        JobStatus.SUCCEEDED,
        result_summary={"success": True},
    )
    return repository


def _request() -> dict:
    return {
        "job_attempt_request": {"job_id": "job-1"},
        "terminal_job_evidence_retained": False,
        "terminal_job_trusted": False,
        "net_return_series_available": False,
    }


def test_backtest_edge_binds_trusted_job_evidence(tmp_path, monkeypatch) -> None:
    path = tmp_path / "graph.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    _prepare(path)

    result = advance_graph_branch(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        edge_id="backtest__statistical_robustness",
        evidence=_request(),
    )

    assert result["current_node"] == "statistical_robustness"
    with connect_sqlite(path) as conn:
        trace = orjson.loads(conn.execute(
            """
            SELECT evidence_json FROM research_graph_trace
            WHERE trace_id=(SELECT latest_trace_id
              FROM research_graph_branches WHERE branch_id='branch-1')
            """
        ).fetchone()["evidence_json"])
    assert "job_attempt_request" not in trace
    assert "terminal_job_trusted" not in trace
    envelope = trace["server_evidence"]["job_attempt"]
    assert envelope["facts"]["net_return_series_available"] is True
    assert envelope["identity_refs"]["trial_plan_hash"] == PLAN_HASH


def test_generic_result_cannot_certify_net_returns(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "graph.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    repository = _prepare(path)
    with connect_sqlite(path) as conn:
        conn.execute(
            """
            UPDATE research_job_artifacts
            SET name='result' WHERE job_id='job-1'
            """
        )

    forged = _request()
    forged["terminal_job_evidence_retained"] = True
    forged["terminal_job_trusted"] = True
    forged["net_return_series_available"] = True
    with pytest.raises(ValueError, match="net_return_series_available"):
        advance_graph_branch(
            instance_id="instance-1",
            branch_id="branch-1",
            owner="alice",
            edge_id="backtest__statistical_robustness",
            evidence=forged,
        )
    assert repository.require("job-1").status is JobStatus.SUCCEEDED


def test_job_from_other_branch_is_rejected(tmp_path, monkeypatch) -> None:
    path = tmp_path / "graph.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    _prepare(path, run_branch="branch-other")

    with pytest.raises(ValueError, match="Graph branch"):
        advance_graph_branch(
            instance_id="instance-1",
            branch_id="branch-1",
            owner="alice",
            edge_id="backtest__statistical_robustness",
            evidence=_request(),
        )
