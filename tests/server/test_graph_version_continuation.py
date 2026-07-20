"""Immutable cross-version continuation of trusted Job evidence."""

from __future__ import annotations

from copy import deepcopy

import orjson
import pytest

import settings as Settings
from server.services.maintenance_cases import (
    MaintenanceCaseStore,
    approve_gate,
    open_gate,
    record_gate_grill,
    record_gate_review,
    record_gate_validation,
)
from server.services.research_graph.branch.continuation import (
    continue_graph_branch,
    preview_graph_continuation,
)
from server.services.research_graph.branch import (
    continuation as continuation_module,
)
from server.services.research_graph.branch.transition import (
    advance_graph_branch,
)
from server.services.research_graph.branch.repository import (
    load_instance_branch_row,
)
from server.services.research_graph.shadow_trace import replay_shadow_trace
from tests.server.test_job_graph_evidence import (
    _graph,
    _prepare,
    _request,
)
from tools.data.sqlite.db import connect_sqlite


def _install_active_target(path) -> dict:
    target = deepcopy(_graph())
    target.update({
        "version": 2,
        "parent_version": 1,
        "lifecycle": "draft",
        "content_hash": "d" * 64,
    })
    with connect_sqlite(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS active_research_graphs (
                graph_id TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                activated_by TEXT NOT NULL,
                activated_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO research_graph_versions (
                graph_id, version, lifecycle, content_hash, parent_version,
                graph_json, created_by, created_at
            ) VALUES ('factor-research', 2, 'draft', ?, 1, ?, 'alice', 2)
            """,
            (
                target["content_hash"],
                orjson.dumps(target).decode(),
            ),
        )
        conn.execute(
            """
            INSERT INTO active_research_graphs (
                graph_id, version, activated_by, activated_at
            ) VALUES ('factor-research', 2, 'alice', 2)
            ON CONFLICT(graph_id) DO UPDATE SET
                version=excluded.version,
                activated_by=excluded.activated_by,
                activated_at=excluded.activated_at
            """
        )
    return target


def _pause_after_bound_job(path) -> None:
    advance_graph_branch(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        edge_id="backtest__job_evidence_ready",
        evidence=_request(),
    )
    advance_graph_branch(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        edge_id="job_evidence_ready__capability_gap",
        evidence={"mandatory_binding_missing": True},
    )


def _pause_legacy_branch_without_bound_job(path) -> None:
    with connect_sqlite(path) as conn:
        latest = orjson.loads(conn.execute(
            """
            SELECT t.evidence_json
            FROM research_graph_branches b
            JOIN research_graph_trace t ON t.trace_id=b.latest_trace_id
            WHERE b.branch_id='branch-1'
            """
        ).fetchone()["evidence_json"])
        evidence = {
            "mandatory_binding_missing": True,
            "research_cycle_checkpoint": latest[
                "research_cycle_checkpoint"
            ],
        }
        conn.execute(
            """
            INSERT INTO research_graph_trace (
                trace_id, instance_id, branch_id, edge_id, from_node, to_node,
                evidence_json, telemetry_json, actor, created_at
            ) VALUES (
                'trace-legacy-gap', 'instance-1', 'branch-1',
                'any_node__capability_gap', 'authoritative_backtest',
                'capability_gap', ?, '{}', 'alice', 2
            )
            """,
            (orjson.dumps(evidence).decode(),),
        )
        conn.execute(
            """
            UPDATE research_graph_branches
            SET current_node='capability_gap', status='paused',
                latest_trace_id='trace-legacy-gap'
            WHERE branch_id='branch-1'
            """
        )


def _approve(path, *, target_hash: str) -> str:
    store = MaintenanceCaseStore(path)
    coordinator = "agent:server-maintenance"
    case = open_gate(
        store,
        owner_user_id="alice",
        coordinator_agent_id=coordinator,
        proposal_ref="proposal:graph-continuation",
        proposer_identity_ref="identity:planning-agent",
        action="continue_graph_branch",
        target_hash=target_hash,
        conversation_ref="auth-conversation:grill-146",
        proposal_evidence_refs=["test:continuation-validation"],
    )
    record_gate_review(
        store,
        owner_user_id="alice",
        case_id=case["case_id"],
        coordinator_agent_id=coordinator,
        reviewer_identity_ref="identity:independent-reviewer",
        disposition="approved",
        evidence_refs=["test:continuation-review"],
    )
    record_gate_validation(
        store,
        owner_user_id="alice",
        case_id=case["case_id"],
        coordinator_agent_id=coordinator,
        validation_summary_hash="e" * 64,
    )
    record_gate_grill(
        store,
        owner_user_id="alice",
        case_id=case["case_id"],
        coordinator_agent_id=coordinator,
        disposition="approved",
        grill_ref="conversation-result:grill-146",
    )
    approve_gate(
        store,
        owner_user_id="alice",
        case_id=case["case_id"],
        coordinator_agent_id=coordinator,
        action="continue_graph_branch",
        target_hash=target_hash,
        approval_ref="approval:grill-146",
    )
    return str(case["case_id"])


def test_continuation_preserves_source_and_projects_job_into_v2(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "graph.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    _prepare(path)
    _pause_legacy_branch_without_bound_job(path)
    target = _install_active_target(path)
    preview = preview_graph_continuation(
        source_instance_id="instance-1",
        source_branch_id="branch-1",
        owner="alice",
        target_graph_version=2,
        job_id="job-1",
    )
    case_id = _approve(path, target_hash=preview["target_hash"])

    continued = continue_graph_branch(
        source_instance_id="instance-1",
        source_branch_id="branch-1",
        owner="alice",
        target_graph_version=2,
        job_id="job-1",
        expected_target_hash=preview["target_hash"],
        human_authorization_id=case_id,
    )

    assert continued["graph_version"] == 2
    branch = continued["branches"][0]
    assert branch["current_node"] == "job_evidence_ready"
    assert branch["status"] == "running"
    assert continued["instance_id"] != "instance-1"
    assert branch["branch_id"] != "branch-1"
    with connect_sqlite(path) as conn:
        source = conn.execute(
            """
            SELECT i.graph_version, b.current_node, b.status, b.latest_trace_id
            FROM research_graph_instances i
            JOIN research_graph_branches b ON b.instance_id=i.instance_id
            WHERE i.instance_id='instance-1' AND b.branch_id='branch-1'
            """
        ).fetchone()
        trace = conn.execute(
            """
            SELECT edge_id, evidence_json FROM research_graph_trace
            WHERE instance_id=? AND branch_id=?
            """,
            (continued["instance_id"], branch["branch_id"]),
        ).fetchone()
        binding = conn.execute(
            """
            SELECT graph_instance_id AS instance_id,
                   graph_branch_id AS branch_id
            FROM research_runs
            WHERE run_id='run-1'
            """
        ).fetchone()
        job_count = conn.execute(
            "SELECT COUNT(*) AS count FROM research_jobs"
        ).fetchone()["count"]
        runtime = load_instance_branch_row(
            conn,
            instance_id=continued["instance_id"],
            branch_id=branch["branch_id"],
            owner="alice",
        )
    assert dict(source) == {
        "graph_version": 1,
        "current_node": "capability_gap",
        "status": "paused",
        "latest_trace_id": source["latest_trace_id"],
    }
    assert trace["edge_id"] == "__graph_continuation__"
    evidence = orjson.loads(trace["evidence_json"])
    assert evidence["graph_continuation"]["source_branch_id"] == "branch-1"
    assert (
        evidence["server_evidence"]["job_attempt"]["facts"]["job_id"]
        == "job-1"
    )
    assert dict(binding) == {
        "instance_id": "instance-1",
        "branch_id": "branch-1",
    }
    assert job_count == 1
    assert runtime is not None
    assert replay_shadow_trace(
        graph=target,
        runtime=runtime,
    )["passed"] is True


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("source_graph_hash", "1" * 64),
        ("source_trace_id", "trace-tampered"),
        ("source_checkpoint_hash", "2" * 64),
        ("target_graph_hash", "3" * 64),
        ("job_evidence_hash", "4" * 64),
        ("authorization_ref", "maintenance-case:missing"),
    ],
)
def test_continuation_shadow_replay_rejects_tampered_lineage(
    tmp_path,
    monkeypatch,
    field,
    replacement,
) -> None:
    path = tmp_path / "graph.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    _prepare(path)
    _pause_legacy_branch_without_bound_job(path)
    target = _install_active_target(path)
    preview = preview_graph_continuation(
        source_instance_id="instance-1",
        source_branch_id="branch-1",
        owner="alice",
        target_graph_version=2,
        job_id="job-1",
    )
    case_id = _approve(path, target_hash=preview["target_hash"])
    continued = continue_graph_branch(
        source_instance_id="instance-1",
        source_branch_id="branch-1",
        owner="alice",
        target_graph_version=2,
        job_id="job-1",
        expected_target_hash=preview["target_hash"],
        human_authorization_id=case_id,
    )
    branch = continued["branches"][0]
    with connect_sqlite(path) as conn:
        trace = conn.execute(
            """
            SELECT trace_id, evidence_json FROM research_graph_trace
            WHERE instance_id=? AND branch_id=?
            """,
            (continued["instance_id"], branch["branch_id"]),
        ).fetchone()
        evidence = orjson.loads(trace["evidence_json"])
        evidence["graph_continuation"][field] = replacement
        conn.execute(
            """
            UPDATE research_graph_trace SET evidence_json=?
            WHERE trace_id=?
            """,
            (orjson.dumps(evidence).decode(), trace["trace_id"]),
        )
        runtime = load_instance_branch_row(
            conn,
            instance_id=continued["instance_id"],
            branch_id=branch["branch_id"],
            owner="alice",
        )
    assert runtime is not None
    assert replay_shadow_trace(
        graph=target,
        runtime=runtime,
    )["passed"] is False


def test_continuation_rejects_stale_trial_identity_without_consuming_gate(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "graph.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    _prepare(path)
    _pause_after_bound_job(path)
    _install_active_target(path)
    preview = preview_graph_continuation(
        source_instance_id="instance-1",
        source_branch_id="branch-1",
        owner="alice",
        target_graph_version=2,
        job_id="job-1",
    )
    case_id = _approve(path, target_hash=preview["target_hash"])
    with connect_sqlite(path) as conn:
        conn.execute(
            """
            UPDATE research_graph_branches
            SET current_trial_plan_hash=?
            WHERE branch_id='branch-1'
            """,
            ("9" * 64,),
        )

    with pytest.raises(ValueError, match="TrialPlan"):
        continue_graph_branch(
            source_instance_id="instance-1",
            source_branch_id="branch-1",
            owner="alice",
            target_graph_version=2,
            job_id="job-1",
            expected_target_hash=preview["target_hash"],
            human_authorization_id=case_id,
        )

    assert MaintenanceCaseStore(path).load_case(
        owner_user_id="alice",
        case_id=case_id,
    )["status"] == "blocked"
    with connect_sqlite(path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM research_graph_instances"
        ).fetchone()[0] == 1


def test_continuation_rolls_back_gate_when_branch_insert_fails(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "graph.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    _prepare(path)
    _pause_legacy_branch_without_bound_job(path)
    _install_active_target(path)
    preview = preview_graph_continuation(
        source_instance_id="instance-1",
        source_branch_id="branch-1",
        owner="alice",
        target_graph_version=2,
        job_id="job-1",
    )
    case_id = _approve(path, target_hash=preview["target_hash"])
    def fail_insert(*_args, **_kwargs) -> None:
        raise RuntimeError("injected insert failure")

    monkeypatch.setattr(
        continuation_module,
        "_insert_continuation",
        fail_insert,
    )

    with pytest.raises(RuntimeError, match="injected insert failure"):
        continue_graph_branch(
            source_instance_id="instance-1",
            source_branch_id="branch-1",
            owner="alice",
            target_graph_version=2,
            job_id="job-1",
            expected_target_hash=preview["target_hash"],
            human_authorization_id=case_id,
        )

    assert MaintenanceCaseStore(path).load_case(
        owner_user_id="alice",
        case_id=case_id,
    )["status"] == "blocked"
    with connect_sqlite(path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM research_graph_instances"
        ).fetchone()[0] == 1
