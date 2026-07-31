from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import orjson

import settings as Settings
from cli_anything.factortester_research.core.draft_graph import (
    build_draft_graph,
)
from cli_anything.factortester_research.core.successor_graph import (
    build_successor_graph,
)
from server.services.research_graph.branch.continuation import (
    continue_graph_branch,
    preview_graph_continuation,
)
from server.services.research_graph.branch.capability_detour import (
    load_or_reconstruct as load_capability_detour,
)
from server.services.research_graph.branch.report_coverage import (
    expected_report_bindings,
)
from server.services.research_graph.branch.repository import (
    load_instance_branch_with_latest_trace,
)
from server.services.research_graph.branch.transition import (
    advance_graph_branch,
)
from server.services.research_graph.shadow_trace import replay_shadow_trace
from server.services.research_graph.protocol import graph_content_hash
from server.services.research_graph.report_checkpoint import (
    report_checkpoint_projection,
)
from server.services.research_graph.research_cycle.replay import (
    validate_research_cycle_checkpoint,
)
from tools.cli.release.research_reporting.publisher.carrier import (
    canonical_carrier,
)
from tools.cli.release.research_reporting.report_items import (
    report_fragment_hash,
)
from tests.server.test_graph_version_continuation import _prepare
from tools.data.sqlite.db import connect_sqlite


_TRACE_PATH = (
    ("t1", "any_node__capability_gap",
     "hypothesis_preregistration", "capability_gap"),
    ("t2", "capability_gap__capability_resolution",
     "capability_gap", "capability_resolution"),
    ("t3", "capability_resolution__capability_gap",
     "capability_resolution", "capability_gap"),
    ("t4", "capability_gap__capability_resolution",
     "capability_gap", "capability_resolution"),
    ("t5", "capability_resolution__capability_gap",
     "capability_resolution", "capability_gap"),
)


def _node(graph: dict, node_id: str) -> dict:
    return next(
        item for item in graph["nodes"] if item["node_id"] == node_id
    )


def _edge(graph: dict, edge_id: str) -> dict:
    return next(
        item for item in graph["edges"] if item["edge_id"] == edge_id
    )


def _unclassified_assessment() -> dict:
    return {
        "requirement_id": "other.unclassified_material_question",
        "applicability": {
            "status": "not_applicable",
            "reason_zh": "当前步骤只延续已登记的同一能力缺口。",
            "fact_refs": ["graph-continuation:existing-capability-detour"],
        },
        "coverage": {
            "decision": "no_material_issue",
            "obligation_refs": [],
        },
        "resolution": {
            "route": "existing_evidence",
            "reuse_status": "exact",
            "validation_refs": ["trace:t5"],
        },
        "entry_effect": {
            "status": "pass",
            "limitation_refs": [],
        },
    }


def _transition_evidence(
    graph: dict,
    *,
    source_node: str,
    edge_id: str,
    target_node: str,
    target_capability_resolution: dict | None = None,
) -> dict:
    assessments = [_unclassified_assessment()]
    evidence = {"entry_requirement_assessments": assessments}
    if target_capability_resolution is not None:
        evidence["target_capability_resolution"] = (
            target_capability_resolution
        )
    bindings = expected_report_bindings(
        graph=graph,
        source_node=_node(graph, source_node),
        edge=_edge(graph, edge_id),
        target_node=_node(graph, target_node),
        entry_assessments=assessments,
        transition_evidence=evidence,
    )
    items = [
        {
            "report_requirement_id": item["report_requirement_id"],
            "subject_ref": item["subject_ref"],
            "content_kind": item["allowed_content"][0],
            "item_hash": hashlib.sha256(
                (
                    item["report_requirement_id"]
                    + "|"
                    + item["subject_ref"]
                ).encode()
            ).hexdigest(),
        }
        for item in bindings
    ]
    evidence["report_submission"] = {
        "schema_version": 1,
        "fragment_hash": report_fragment_hash(items),
        "items": items,
    }
    return evidence


def _recovery_checkpoint() -> dict:
    return validate_research_cycle_checkpoint({
        "schema_version": 1,
        "contract_hash": "1" * 64,
        "trial_plan_hash": "",
        "methodology_hash": "2" * 64,
        "claims": [],
        "obligations": [{
            "schema_version": 1,
            "obligation_id": "capability-detour-recovery",
            "contract_hash": "1" * 64,
            "claim_ids": [],
            "obligation_kind": "capability_detour_recovery",
            "title_zh": "能力绕行恢复",
            "epistemic_question": (
                "Has the inherited capability detour been repaired?"
            ),
            "scope": {"graph_upgrade": "v8-to-v10"},
            "discharge_criterion": {
                "rule_ref": "graph-rule:capability-detour-recovery",
            },
            "status": "discharged",
            "materiality": "decision_blocking",
            "methodology_hash": "2" * 64,
            "created_event_ref": "trace:t5",
            "requirement_refs": [
                "other.unclassified_material_question",
            ],
        }],
        "pending_adjudications": [],
        "pending_closure": None,
        "closure": None,
    })


def _coverage_submission(
    path,
    *,
    instance_id: str,
    branch_id: str,
    graph: dict,
    source_node: str,
    edge_id: str,
    target_node: str,
) -> dict:
    with connect_sqlite(path) as conn:
        runtime = load_instance_branch_with_latest_trace(
            conn,
            instance_id=instance_id,
            branch_id=branch_id,
            owner="alice",
        )
    requirement_id = "other.unclassified_material_question"
    value = {
        "schema_version": 1,
        "branch_ref": f"graph-branch:{instance_id}:{branch_id}",
        "graph_ref": f"{graph['graph_id']}@v{graph['version']}",
        "current_node": source_node,
        "context_ref": "sha256:" + "c" * 64,
        "checkpoint_ref": f"trace:{runtime['latest_trace_id']}",
        "edge_id": edge_id,
        "target_node": target_node,
        "coverage": [{
            "requirement_id": requirement_id,
            "obligation_refs": [
                "obligation:capability-detour-recovery",
            ],
            "obligation_statuses": ["discharged"],
            "node_required": requirement_id in (
                _node(graph, source_node).get("entry_requirement_refs") or []
            ),
            "edge_required": requirement_id in (
                _edge(graph, edge_id).get(
                    "obligation_requirement_refs"
                ) or []
            ),
            "satisfaction": "satisfied",
        }],
    }
    value["coverage_hash"] = "sha256:" + hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    value["prepared_git_commit"] = "a" * 40
    return value


def _install_recovery_obligation(
    path,
    *,
    instance_id: str,
    branch_id: str,
) -> None:
    """Seed the accepted obligation state exercised by this recovery test."""
    with connect_sqlite(path) as conn:
        runtime = load_instance_branch_with_latest_trace(
            conn,
            instance_id=instance_id,
            branch_id=branch_id,
            owner="alice",
        )
        evidence = orjson.loads(runtime["latest_trace_evidence_json"])
        evidence["research_cycle_checkpoint"] = _recovery_checkpoint()
        conn.execute(
            "UPDATE research_graph_trace SET evidence_json=? "
            "WHERE trace_id=?",
            (
                orjson.dumps(evidence).decode(),
                runtime["latest_trace_id"],
            ),
        )


def _target_resolution(graph: dict, node_id: str) -> dict:
    node = _node(graph, node_id)
    return {
        "node_id": node_id,
        "bindings": [
            {
                "capability_id": capability_id,
                **graph["capability_descriptors"][capability_id],
            }
            for capability_id in node.get("required_capabilities") or []
        ],
        "gaps": [],
        "triggered_conditional_bindings": [],
        "undetermined_conditions": [],
    }


def _install_real_v8_shape(path) -> dict:
    _prepare(path)
    source = build_draft_graph()
    intermediate = deepcopy(source)
    intermediate["version"] = 9
    intermediate["parent_version"] = 8
    intermediate["content_hash"] = graph_content_hash(intermediate)
    target = build_successor_graph()
    with connect_sqlite(path) as conn:
        conn.execute("DELETE FROM research_graph_trace")
        conn.execute(
            "UPDATE research_graph_versions SET version=8, "
            "parent_version=7, content_hash=?, graph_json=?",
            (source["content_hash"], orjson.dumps(source).decode()),
        )
        conn.execute(
            "UPDATE research_graph_instances SET graph_version=8 "
            "WHERE instance_id='instance-1'"
        )
        conn.executemany(
            """
            INSERT INTO research_graph_trace (
                trace_id, instance_id, branch_id, edge_id, from_node, to_node,
                evidence_json, telemetry_json, actor, created_at
            ) VALUES (?, 'instance-1', 'branch-1', ?, ?, ?, '{}', '{}',
                      'alice', ?)
            """,
            [(*row, index) for index, row in enumerate(_TRACE_PATH, 1)],
        )
        conn.execute(
            """
            UPDATE research_graph_branches
            SET current_node='capability_gap', status='paused',
                latest_trace_id='t5', current_trial_plan_hash='',
                trial_stage_projection_json='{}'
            WHERE branch_id='branch-1'
            """
        )
        conn.execute(
            """
            INSERT INTO research_graph_versions (
                graph_id, version, lifecycle, content_hash, parent_version,
                graph_json, created_by, created_at
            ) VALUES ('factor-research', 9, 'draft', ?, 8, ?, 'server', 9)
            """,
            (
                intermediate["content_hash"],
                orjson.dumps(intermediate).decode(),
            ),
        )
        conn.execute(
            """
            INSERT INTO research_graph_versions (
                graph_id, version, lifecycle, content_hash, parent_version,
                graph_json, created_by, created_at
            ) VALUES ('factor-research', 10, 'draft', ?, 9, ?, 'server', 10)
            """,
            (target["content_hash"], orjson.dumps(target).decode()),
        )
        conn.execute(
            """
            CREATE TABLE active_research_graphs (
                graph_id TEXT PRIMARY KEY, version INTEGER NOT NULL,
                activated_by TEXT NOT NULL, activated_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO active_research_graphs VALUES "
            "('factor-research', 10, 'server', 10)"
        )
    return target


def test_real_v8_shape_continues_once_through_v9_to_v10_and_replays(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "descendant.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    target = _install_real_v8_shape(path)

    preview = preview_graph_continuation(
        source_instance_id="instance-1",
        source_branch_id="branch-1",
        owner="alice",
        target_graph_version=10,
        job_id="",
    )
    descriptor = preview["descriptor"]
    assert descriptor["source_graph_version"] == 8
    assert descriptor["target_graph_version"] == 10
    assert descriptor["lineage_versions"] == [8, 9, 10]
    assert len(descriptor["cumulative_change_manifest_hash"]) == 64
    assert [
        item["version"]
        for item in descriptor["cumulative_change_manifests"]
    ] == [9, 10]
    assert {
        "change.remove-global-pit-gate",
        "change.capability-detour-resume",
        "change.report-container-routing",
    } <= set(
        descriptor["cumulative_change_manifests"][-1]["change_ids"]
    )
    assert descriptor["capability_detour"]["resume_node"] == (
        "hypothesis_preregistration"
    )
    assert descriptor["legacy_cycle_bootstrap"]["mode"] == (
        "legacy_empty_pretrial"
    )
    assert descriptor["entry_resolution_stack_depth"] == 1
    assert len(descriptor["entry_resolution_stack_hash"]) == 64

    continued = continue_graph_branch(
        source_instance_id="instance-1",
        source_branch_id="branch-1",
        owner="alice",
        target_graph_version=10,
        job_id="",
        expected_target_hash=preview["target_hash"],
    )
    branch = continued["branches"][0]
    with connect_sqlite(path) as conn:
        runtime = load_instance_branch_with_latest_trace(
            conn,
            instance_id=continued["instance_id"],
            branch_id=branch["branch_id"],
            owner="alice",
        )
        evidence = orjson.loads(runtime["latest_trace_evidence_json"])
        trace_created_at = float(conn.execute(
            "SELECT created_at FROM research_graph_trace WHERE trace_id=?",
            (runtime["latest_trace_id"],),
        ).fetchone()["created_at"])
    assert continued["graph_version"] == 10
    assert branch["current_node"] == "capability_gap"
    assert [
        item["event"]
        for item in evidence["entry_resolution_event"]["events"]
    ] == ["push"]
    carrier = report_checkpoint_projection(
        instance_id=continued["instance_id"],
        work_package_id=continued["work_package_id"],
        branch_id=branch["branch_id"],
        workspace_id="workspace-1",
        graph_id="factor-research",
        graph_version=10,
        title="因子研究报告",
        product_group="CNFutures",
        current_node=branch["current_node"],
        status=branch["status"],
        trace_id=str(runtime["latest_trace_id"]),
        edge_id="__graph_continuation__",
        from_node=branch["current_node"],
        created_at=trace_created_at,
        checkpoint=evidence["research_cycle_checkpoint"],
        trace_evidence=evidence,
        evidence_refs=evidence.get("evidence_refs") or [],
    )
    assert canonical_carrier(carrier)["latest_transition"][
        "entry_resolution_event"
    ] == evidence["entry_resolution_event"]
    replay = replay_shadow_trace(graph=target, runtime=runtime)
    assert replay["passed"] is True, replay


def test_v8_gap_reentry_repairs_then_resumes_before_node_local_v10_work(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "gap-reentry.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    target = _install_real_v8_shape(path)
    preview = preview_graph_continuation(
        source_instance_id="instance-1",
        source_branch_id="branch-1",
        owner="alice",
        target_graph_version=10,
        job_id="",
    )
    continued = continue_graph_branch(
        source_instance_id="instance-1",
        source_branch_id="branch-1",
        owner="alice",
        target_graph_version=10,
        job_id="",
        expected_target_hash=preview["target_hash"],
    )
    instance_id = continued["instance_id"]
    branch_id = continued["branches"][0]["branch_id"]
    _install_recovery_obligation(
        path,
        instance_id=instance_id,
        branch_id=branch_id,
    )

    repair_evidence = _transition_evidence(
        target,
        source_node="capability_gap",
        edge_id="capability_gap__code_improvement",
        target_node="code_improvement_required",
    )
    repair_evidence["obligation_coverage_submission"] = (
        _coverage_submission(
            path,
            instance_id=instance_id,
            branch_id=branch_id,
            graph=target,
            source_node="capability_gap",
            edge_id="capability_gap__code_improvement",
            target_node="code_improvement_required",
        )
    )
    repair = advance_graph_branch(
        instance_id=instance_id,
        branch_id=branch_id,
        owner="alice",
        edge_id="capability_gap__code_improvement",
        evidence=repair_evidence,
    )
    assert repair["current_node"] == "code_improvement_required"
    assert repair["capability_detour"]["status"] == "retained"

    resolved_evidence = _transition_evidence(
        target,
        source_node="code_improvement_required",
        edge_id="code_improvement__capability_resolution",
        target_node="capability_resolution",
    )
    resolved_evidence["obligation_coverage_submission"] = (
        _coverage_submission(
            path,
            instance_id=instance_id,
            branch_id=branch_id,
            graph=target,
            source_node="code_improvement_required",
            edge_id="code_improvement__capability_resolution",
            target_node="capability_resolution",
        )
    )
    resolved = advance_graph_branch(
        instance_id=instance_id,
        branch_id=branch_id,
        owner="alice",
        edge_id="code_improvement__capability_resolution",
        evidence=resolved_evidence,
    )
    assert resolved["current_node"] == "capability_resolution"
    assert resolved["capability_detour"]["status"] == "retained"

    resume_edge = (
        "capability_resolution__resume_hypothesis_preregistration"
    )
    resumed_evidence = _transition_evidence(
        target,
        source_node="capability_resolution",
        edge_id=resume_edge,
        target_node="hypothesis_preregistration",
        target_capability_resolution=_target_resolution(
            target,
            "hypothesis_preregistration",
        ),
    )
    resumed_evidence["obligation_coverage_submission"] = (
        _coverage_submission(
            path,
            instance_id=instance_id,
            branch_id=branch_id,
            graph=target,
            source_node="capability_resolution",
            edge_id=resume_edge,
            target_node="hypothesis_preregistration",
        )
    )
    resumed = advance_graph_branch(
        instance_id=instance_id,
        branch_id=branch_id,
        owner="alice",
        edge_id=resume_edge,
        evidence=resumed_evidence,
    )
    assert resumed["current_node"] == "hypothesis_preregistration"
    assert resumed["capability_detour"]["status"] == "resumed"

    with connect_sqlite(path) as conn:
        assert load_capability_detour(
            conn,
            instance_id=instance_id,
            branch_id=branch_id,
        ) is None
        runtime = load_instance_branch_with_latest_trace(
            conn,
            instance_id=instance_id,
            branch_id=branch_id,
            owner="alice",
        )
    frame = orjson.loads(runtime["entry_resolution_frame_json"])
    assert len(frame["frames"]) == 1
    assert frame["frames"][0]["target_node"] == (
        "hypothesis_preregistration"
    )
    assert frame["frames"][0]["status"] == "resolving"
    assert set(frame["frames"][0]["unresolved_entry_requirement_refs"]) == (
        set(_node(
            target,
            "hypothesis_preregistration",
        )["entry_requirement_refs"])
    )


def test_shadow_rejects_tampered_continuation_entry_stack_event(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "tampered-entry-event.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    target = _install_real_v8_shape(path)
    preview = preview_graph_continuation(
        source_instance_id="instance-1",
        source_branch_id="branch-1",
        owner="alice",
        target_graph_version=10,
        job_id="",
    )
    continued = continue_graph_branch(
        source_instance_id="instance-1",
        source_branch_id="branch-1",
        owner="alice",
        target_graph_version=10,
        job_id="",
        expected_target_hash=preview["target_hash"],
    )
    branch = continued["branches"][0]
    with connect_sqlite(path) as conn:
        trace = conn.execute(
            "SELECT trace_id, evidence_json FROM research_graph_trace "
            "WHERE instance_id=? AND branch_id=?",
            (continued["instance_id"], branch["branch_id"]),
        ).fetchone()
        evidence = orjson.loads(trace["evidence_json"])
        evidence["entry_resolution_event"]["stack_hash_after"] = "0" * 64
        conn.execute(
            "UPDATE research_graph_trace SET evidence_json=? WHERE trace_id=?",
            (orjson.dumps(evidence).decode(), trace["trace_id"]),
        )
        runtime = load_instance_branch_with_latest_trace(
            conn,
            instance_id=continued["instance_id"],
            branch_id=branch["branch_id"],
            owner="alice",
        )

    assert replay_shadow_trace(graph=target, runtime=runtime)["passed"] is False


def test_shadow_rejects_tampered_cumulative_graph_lineage(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "tampered-lineage.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    target = _install_real_v8_shape(path)
    preview = preview_graph_continuation(
        source_instance_id="instance-1",
        source_branch_id="branch-1",
        owner="alice",
        target_graph_version=10,
        job_id="",
    )
    continued = continue_graph_branch(
        source_instance_id="instance-1",
        source_branch_id="branch-1",
        owner="alice",
        target_graph_version=10,
        job_id="",
        expected_target_hash=preview["target_hash"],
    )
    branch = continued["branches"][0]
    with connect_sqlite(path) as conn:
        trace = conn.execute(
            "SELECT trace_id, evidence_json FROM research_graph_trace "
            "WHERE instance_id=? AND branch_id=?",
            (continued["instance_id"], branch["branch_id"]),
        ).fetchone()
        evidence = orjson.loads(trace["evidence_json"])
        evidence["graph_continuation"]["lineage_path_hash"] = "0" * 64
        conn.execute(
            "UPDATE research_graph_trace SET evidence_json=? WHERE trace_id=?",
            (orjson.dumps(evidence).decode(), trace["trace_id"]),
        )
        runtime = load_instance_branch_with_latest_trace(
            conn,
            instance_id=continued["instance_id"],
            branch_id=branch["branch_id"],
            owner="alice",
        )

    assert replay_shadow_trace(graph=target, runtime=runtime)["passed"] is False
