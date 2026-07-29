from __future__ import annotations

import orjson

import settings as Settings
from server.services.research_graph.branch.continuation import (
    continue_graph_branch,
    preview_graph_continuation,
)
from server.services.research_graph.branch.repository import (
    load_instance_branch_with_latest_trace,
)
from server.services.research_graph.shadow_trace import replay_shadow_trace
from tests.server.test_graph_version_continuation import (
    _install_active_target,
    _prepare,
)
from tools.data.sqlite.db import connect_sqlite


def _legacy_pretrial(path) -> None:
    _prepare(path)
    source = {
        "schema_version": 1,
        "graph_id": "factor-research",
        "version": 1,
        "lifecycle": "active",
        "content_hash": "c" * 64,
        "entry_node": "hypothesis_preregistration",
        "nodes": [
            {
                "node_id": "hypothesis_preregistration",
                "kind": "research",
                "required_capabilities": [],
            },
            {
                "node_id": "capability_gap",
                "kind": "capability_gap",
                "required_capabilities": [],
            },
        ],
        "edges": [{
            "edge_id": "any_node__capability_gap",
            "from_node": "*",
            "to_node": "capability_gap",
            "edge_type": "failure",
            "guard": {},
            "required_evidence": [],
        }],
    }
    with connect_sqlite(path) as conn:
        conn.execute(
            """
            UPDATE research_graph_versions SET graph_json=?
            WHERE graph_id='factor-research' AND version=1
            """,
            (orjson.dumps(source).decode(),),
        )
        conn.execute(
            """
            UPDATE research_graph_trace
            SET edge_id='any_node__capability_gap',
                from_node='hypothesis_preregistration',
                to_node='capability_gap', evidence_json='{}'
            WHERE trace_id='trace-bootstrap'
            """
        )
        conn.execute(
            """
            UPDATE research_graph_branches
            SET current_node='capability_gap', status='paused',
                current_trial_plan_hash='', trial_stage_projection_json='{}'
            WHERE branch_id='branch-1'
            """
        )


def _schema_v2_target(path) -> dict:
    target = _install_active_target(path)
    target["schema_version"] = 2
    target["content_hash"] = "9" * 64
    with connect_sqlite(path) as conn:
        conn.execute(
            """
            UPDATE research_graph_versions SET content_hash=?, graph_json=?
            WHERE graph_id='factor-research' AND version=2
            """,
            (target["content_hash"], orjson.dumps(target).decode()),
        )
    return target


def test_legacy_pretrial_continuation_bootstraps_empty_cycle(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "graph.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    _legacy_pretrial(path)
    target = _schema_v2_target(path)

    preview = preview_graph_continuation(
        source_instance_id="instance-1",
        source_branch_id="branch-1",
        owner="alice",
        target_graph_version=2,
        job_id="",
    )

    bootstrap = preview["descriptor"]["legacy_cycle_bootstrap"]
    assert bootstrap["mode"] == "legacy_empty_pretrial"
    assert bootstrap["source_trace_id"] == "trace-bootstrap"
    assert preview["descriptor"]["capability_detour"]["resume_node"] == (
        "hypothesis_preregistration"
    )
    continued = continue_graph_branch(
        source_instance_id="instance-1",
        source_branch_id="branch-1",
        owner="alice",
        target_graph_version=2,
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

    checkpoint = evidence["research_cycle_checkpoint"]
    assert checkpoint["claims"] == []
    assert checkpoint["obligations"] == []
    replay = replay_shadow_trace(graph=target, runtime=runtime)
    assert replay["passed"] is True, replay
