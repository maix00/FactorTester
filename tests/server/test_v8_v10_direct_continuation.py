from __future__ import annotations

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
from server.services.research_graph.branch.repository import (
    load_instance_branch_with_latest_trace,
)
from server.services.research_graph.shadow_trace import replay_shadow_trace
from server.services.research_graph.report_checkpoint import (
    report_checkpoint_projection,
)
from tools.cli.release.research_reporting.publisher.carrier import (
    canonical_carrier,
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


def _install_real_v8_shape(path) -> dict:
    _prepare(path)
    source = build_draft_graph()
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
            ) VALUES ('factor-research', 10, 'draft', ?, 8, ?, 'server', 10)
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


def test_real_v8_shape_continues_once_to_v10_and_shadow_replays(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "direct.sqlite"
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
