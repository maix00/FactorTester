"""Immutable cross-version continuation of trusted Job evidence."""

from __future__ import annotations

from copy import deepcopy

import orjson
import pytest

import settings as Settings
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
from server.services.research_graph.branch.context import (
    build_graph_branch_context,
)
from server.services.research_graph.branch.repository import (
    load_instance_branch_row,
)
from server.services.research_graph.report_checkpoint import (
    report_checkpoint_projection,
)
from tests.server.test_job_graph_evidence import (
    PLAN_HASH,
    _graph,
    _prepare,
    _request,
)
from tests.server.data_contract_fixtures import initialize
from tools.data.sqlite.db import connect_sqlite


def _install_active_target(
    path,
    *,
    capability_gap_requires_classification: bool = False,
    activate: bool = True,
) -> dict:
    target = deepcopy(_graph())
    target.update({
        "version": 2,
        "parent_version": 1,
        "lifecycle": "draft",
        "content_hash": "d" * 64,
    })
    if capability_gap_requires_classification:
        next(
            node for node in target["nodes"]
            if node["node_id"] == "capability_gap"
        )["required_capabilities"] = ["capability-gap.classify"]
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
        if activate:
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


def _upgrade_active_target_to_schema_v2(
    path,
    *,
    activate: bool = True,
) -> dict:
    target = _install_active_target(path, activate=activate)
    target["schema_version"] = 2
    target["content_hash"] = "9" * 64
    with connect_sqlite(path) as conn:
        conn.execute(
            """
            UPDATE research_graph_trace
            SET edge_id='__legacy_bootstrap__',
                from_node='authoritative_backtest',
                to_node='authoritative_backtest'
            WHERE trace_id='trace-bootstrap'
            """
        )
        conn.execute(
            """
            UPDATE research_graph_versions
            SET content_hash=?, graph_json=?
            WHERE graph_id='factor-research' AND version=2
            """,
            (target["content_hash"], orjson.dumps(target).decode()),
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


def _pause_pretrial_branch(path) -> None:
    with connect_sqlite(path) as conn:
        checkpoint_evidence = conn.execute(
            "SELECT evidence_json FROM research_graph_trace "
            "WHERE trace_id='trace-bootstrap'"
        ).fetchone()["evidence_json"]
        conn.execute(
            """
            INSERT INTO research_graph_trace (
                trace_id, instance_id, branch_id, edge_id, from_node, to_node,
                evidence_json, telemetry_json, actor, created_at
            ) VALUES (
                'trace-pretrial-gap', 'instance-1', 'branch-1',
                'data_contract__capability_gap', 'data_contract',
                'capability_gap', ?, '{}', 'alice', 2
            )
            """,
            (checkpoint_evidence,),
        )
        conn.execute(
            """
            UPDATE research_graph_branches
            SET current_node='capability_gap', status='paused',
                current_trial_plan_hash='',
                latest_trace_id='trace-pretrial-gap'
            WHERE branch_id='branch-1'
            """
        )


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

    continued = continue_graph_branch(
        source_instance_id="instance-1",
        source_branch_id="branch-1",
        owner="alice",
        target_graph_version=2,
        job_id="job-1",
        expected_target_hash=preview["target_hash"],
    )

    assert continued["graph_version"] == 2
    assert continued["work_package_id"] == "instance-1"
    branch = continued["branches"][0]
    assert branch["current_node"] == "job_evidence_ready"
    assert branch["status"] == "running"
    assert branch["hypothesis_branch_id"] == "branch-1"
    assert branch["is_current_incarnation"] is True
    assert continued["instance_id"] != "instance-1"
    assert branch["branch_id"] != "branch-1"
    with connect_sqlite(path) as conn:
        source = conn.execute(
            """
            SELECT i.graph_version, i.work_package_id,
                   b.hypothesis_branch_id, b.is_current_incarnation,
                   b.current_node, b.status, b.latest_trace_id
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
        target_identity = conn.execute(
            """
            SELECT i.work_package_id, b.hypothesis_branch_id,
                   b.is_current_incarnation
            FROM research_graph_instances AS i
            JOIN research_graph_branches AS b
              ON b.instance_id=i.instance_id
            WHERE i.instance_id=? AND b.branch_id=?
            """,
            (continued["instance_id"], branch["branch_id"]),
        ).fetchone()
    assert dict(source) == {
        "graph_version": 1,
        "work_package_id": "instance-1",
        "hypothesis_branch_id": "branch-1",
        "is_current_incarnation": 0,
        "current_node": "capability_gap",
        "status": "paused",
        "latest_trace_id": source["latest_trace_id"],
    }
    assert dict(target_identity) == {
        "work_package_id": "instance-1",
        "hypothesis_branch_id": "branch-1",
        "is_current_incarnation": 1,
    }
    assert trace["edge_id"] == "__graph_continuation__"
    evidence = orjson.loads(trace["evidence_json"])
    assert evidence["graph_continuation"]["schema_version"] == 2
    assert evidence["graph_continuation"]["source_branch_id"] == "branch-1"
    assert evidence["graph_continuation"]["budget_profile_ref"]
    assert len(evidence["graph_continuation"]["budget_profile_hash"]) == 64
    source_trace_ref = (
        "trace:" + evidence["graph_continuation"]["source_trace_id"]
    )
    assert evidence["research_cycle"]["parent_trace_ref"] == source_trace_ref
    assert evidence["report_lineage"] == {
        "status": "linked",
        "predecessor_checkpoint_ref": source_trace_ref,
        "source_branch_ref": "graph-branch:instance-1:branch-1",
    }
    legacy_evidence = deepcopy(evidence)
    legacy_evidence.pop("report_lineage")
    legacy_evidence["research_cycle"]["parent_trace_ref"] = ""
    reportable_checkpoint = {
        "projection_hash": "a" * 64,
        "contract_hash": "1" * 64,
        "methodology_hash": "2" * 64,
        "trial_plan_hash": "",
        "claims": [],
        "obligations": [],
        "closure": None,
    }
    legacy_carrier = report_checkpoint_projection(
        instance_id=continued["instance_id"],
        work_package_id="instance-1",
        branch_id=branch["branch_id"],
        workspace_id="workspace-1",
        graph_id="factor-research",
        graph_version=2,
        title="因子研究报告",
        product_group="CNFutures",
        current_node=branch["current_node"],
        status=branch["status"],
        trace_id=trace["edge_id"].removeprefix("__") + "-fixture",
        edge_id="__graph_continuation__",
        from_node=branch["current_node"],
        created_at=1.0,
        checkpoint=reportable_checkpoint,
        trace_evidence=legacy_evidence,
        evidence_refs=legacy_evidence["evidence_refs"],
    )
    assert legacy_carrier is not None
    assert legacy_carrier["report_lineage"] == evidence["report_lineage"]
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
    paused = advance_graph_branch(
        instance_id=continued["instance_id"],
        branch_id=branch["branch_id"],
        owner="alice",
        edge_id="job_evidence_ready__capability_gap",
        evidence={"mandatory_binding_missing": True},
    )
    assert paused["current_node"] == "capability_gap"
    with connect_sqlite(path) as conn:
        runtime = load_instance_branch_row(
            conn,
            instance_id=continued["instance_id"],
            branch_id=branch["branch_id"],
            owner="alice",
        )
    assert runtime is not None


def test_pretrial_continuation_preserves_paused_gap_without_job_evidence(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "graph.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    initialize(path)
    _pause_pretrial_branch(path)
    target = _install_active_target(
        path,
        capability_gap_requires_classification=True,
    )

    preview = preview_graph_continuation(
        source_instance_id="instance-1",
        source_branch_id="branch-1",
        owner="alice",
        target_graph_version=2,
        job_id="",
    )
    assert preview["descriptor"]["continuation_mode"] == "pre_trial_checkpoint"
    assert preview["descriptor"]["target_node"] == "capability_gap"

    continued = continue_graph_branch(
        source_instance_id="instance-1",
        source_branch_id="branch-1",
        owner="alice",
        target_graph_version=2,
        job_id="",
        expected_target_hash=preview["target_hash"],
    )

    branch = continued["branches"][0]
    assert branch["current_node"] == "capability_gap"
    assert branch["status"] == "paused"
    with connect_sqlite(path) as conn:
        trace = conn.execute(
            """
            SELECT evidence_json FROM research_graph_trace
            WHERE instance_id=? AND branch_id=?
            """,
            (continued["instance_id"], branch["branch_id"]),
        ).fetchone()
        runtime = load_instance_branch_row(
            conn,
            instance_id=continued["instance_id"],
            branch_id=branch["branch_id"],
            owner="alice",
        )
    evidence = orjson.loads(trace["evidence_json"])
    assert "server_evidence" not in evidence
    source_trace_ref = (
        "trace:" + evidence["graph_continuation"]["source_trace_id"]
    )
    assert evidence["research_cycle"]["parent_trace_ref"] == source_trace_ref
    assert evidence["report_lineage"] == {
        "status": "linked",
        "predecessor_checkpoint_ref": source_trace_ref,
        "source_branch_ref": "graph-branch:instance-1:branch-1",
    }
    assert (
        evidence["research_cycle_checkpoint"]["trial_plan_hash"] == ""
    )
    assert runtime is not None
    context = build_graph_branch_context(
        instance_id=continued["instance_id"],
        branch_id=branch["branch_id"],
        owner="alice",
    )
    assert context["required_capabilities"] == [{
        "capability_id": "capability-gap.classify",
        "binding": None,
        "gap": None,
    }]


def test_schema_v2_continuation_checks_current_node_not_history_topology(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "graph.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    _prepare(path)
    target = _upgrade_active_target_to_schema_v2(path)
    historical = next(
        node for node in target["nodes"]
        if node["node_id"] == "job_evidence_ready"
    )
    historical["purpose"] = "A changed historical stage must not be replayed."
    with connect_sqlite(path) as conn:
        conn.execute(
            """
            UPDATE research_graph_versions SET graph_json=?
            WHERE graph_id='factor-research' AND version=2
            """,
            (orjson.dumps(target).decode(),),
        )
        conn.execute(
            """
            INSERT INTO research_graph_trace (
                trace_id, instance_id, branch_id, edge_id,
                from_node, to_node, evidence_json, telemetry_json,
                actor, created_at
            ) VALUES (
                'trace-historical', 'instance-1', 'branch-1',
                'backtest__job_evidence_ready',
                'authoritative_backtest', 'job_evidence_ready',
                '{}', '{}', 'alice', 0.5
            )
            """
        )

    preview = preview_graph_continuation(
        source_instance_id="instance-1",
        source_branch_id="branch-1",
        owner="alice",
        target_graph_version=2,
        job_id="",
    )

    assert preview["descriptor"]["continuation_mode"] == (
        "same_node_reentry"
    )
    assert preview["descriptor"]["target_node"] == (
        "authoritative_backtest"
    )
    assert "topology_preflight" not in preview["descriptor"]
    continued = continue_graph_branch(
        source_instance_id="instance-1",
        source_branch_id="branch-1",
        owner="alice",
        target_graph_version=2,
        job_id="",
        expected_target_hash=preview["target_hash"],
    )

    branch = continued["branches"][0]
    assert branch["current_node"] == "authoritative_backtest"
    assert branch["status"] == "running"
    with connect_sqlite(path) as conn:
        row = conn.execute(
            """
            SELECT current_trial_plan_hash, evidence_refs_json
            FROM research_graph_branches WHERE branch_id=?
            """,
            (branch["branch_id"],),
        ).fetchone()
        trace_evidence = orjson.loads(conn.execute(
            "SELECT evidence_json FROM research_graph_trace "
            "WHERE instance_id=? AND branch_id=?",
            (continued["instance_id"], branch["branch_id"]),
        ).fetchone()["evidence_json"])
    assert row["current_trial_plan_hash"] == PLAN_HASH
    assert orjson.loads(row["evidence_refs_json"]) == []
    assert "entry_resolution_event" not in trace_evidence
    with connect_sqlite(path) as conn:
        runtime = load_instance_branch_row(
            conn,
            instance_id=continued["instance_id"],
            branch_id=branch["branch_id"],
            owner="alice",
        )
    assert runtime is not None


def test_draft_target_rejects_public_continuation(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "graph.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    _prepare(path)
    _upgrade_active_target_to_schema_v2(path, activate=False)

    with pytest.raises(
        ValueError,
        match="Graph continuation target is not active",
    ):
        preview_graph_continuation(
            source_instance_id="instance-1",
            source_branch_id="branch-1",
            owner="alice",
            target_graph_version=2,
            job_id="",
        )


def test_schema_v2_continuation_previews_only_material_requirement_changes(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "graph.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    _prepare(path)
    target = _upgrade_active_target_to_schema_v2(path)
    current = next(
        node for node in target["nodes"]
        if node["node_id"] == "authoritative_backtest"
    )
    current["entry_requirement_refs"] = [
        "data.required_fields",
        "trial_design.strategy_freeze",
    ]
    target["requirement_catalog"] = {
        "catalog_revision": 2,
        "categories": [],
        "requirements": [
            {
                "requirement_id": "data.required_fields",
                "revision": 1,
                "question_zh": "必需字段是否覆盖当前试验？",
            },
            {
                "requirement_id": "trial_design.strategy_freeze",
                "revision": 1,
                "question_zh": "策略变量是否已冻结？",
            },
        ],
    }
    target["content_hash"] = "8" * 64
    with connect_sqlite(path) as conn:
        conn.execute(
            """
            UPDATE research_graph_versions SET content_hash=?, graph_json=?
            WHERE graph_id='factor-research' AND version=2
            """,
            (target["content_hash"], orjson.dumps(target).decode()),
        )

    preview = preview_graph_continuation(
        source_instance_id="instance-1",
        source_branch_id="branch-1",
        owner="alice",
        target_graph_version=2,
        job_id="",
    )

    delta = preview["descriptor"]["requirement_preflight"]
    assert delta["target_node"] == "authoritative_backtest"
    assert delta["catalog_added_count"] == 2
    assert delta["catalog_changed_count"] == 0
    assert delta["catalog_removed_count"] == 0
    assert len(delta["catalog_delta_hash"]) == 64
    assert delta["entry_added_ids"] == [
        "data.required_fields",
        "trial_design.strategy_freeze",
    ]
    assert delta["entry_revised_ids"] == []
    assert delta["entry_metadata_changed_ids"] == []
    assert delta["entry_removed_ids"] == []
    assert delta["assessment_required_ids"] == delta["entry_added_ids"]
    assert len(delta["delta_hash"]) == 64
    continued = continue_graph_branch(
        source_instance_id="instance-1",
        source_branch_id="branch-1",
        owner="alice",
        target_graph_version=2,
        job_id="",
        expected_target_hash=preview["target_hash"],
    )
    branch = continued["branches"][0]
    context = build_graph_branch_context(
        instance_id=continued["instance_id"],
        branch_id=branch["branch_id"],
        owner="alice",
    )
    assert context["entry_resolution"]["status"] == "resolving"
    assert context["entry_resolution"]["target_node"] == (
        "authoritative_backtest"
    )
    assert [
        item["requirement_id"] for item in context["entry_requirements"]
    ] == delta["assessment_required_ids"]


def test_pretrial_continuation_rejects_source_with_trial_plan(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "graph.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    _prepare(path)
    _pause_legacy_branch_without_bound_job(path)
    _install_active_target(
        path,
        capability_gap_requires_classification=True,
    )

    with pytest.raises(ValueError, match="empty TrialPlan"):
        preview_graph_continuation(
            source_instance_id="instance-1",
            source_branch_id="branch-1",
            owner="alice",
            target_graph_version=2,
            job_id="",
        )


def test_continuation_rejects_stale_trial_identity_before_writing(
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
        )

    with connect_sqlite(path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM research_graph_instances"
        ).fetchone()[0] == 1


def test_continuation_is_atomic_when_branch_insert_fails(
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
        )

    with connect_sqlite(path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM research_graph_instances"
        ).fetchone()[0] == 1
