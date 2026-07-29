from __future__ import annotations

import orjson
import pytest

import settings as Settings
from server.services.research_graph.branch.context import (
    build_graph_branch_context,
)
from server.services.research_graph.branch.transition import (
    advance_graph_branch,
)
from tests.server.data_contract_fixtures import initialize
from tools.data.sqlite.db import connect_sqlite


def _graph() -> dict:
    nodes = [
        {"node_id": node_id, "kind": kind, "required_capabilities": []}
        for node_id, kind in (
            ("hypothesis_preregistration", "research"),
            ("data_contract", "validation"),
            ("capability_gap", "capability_gap"),
            ("capability_resolution", "capability"),
        )
    ]
    edges = [
        _edge(
            "hypothesis__capability_resolution",
            "hypothesis_preregistration",
            "capability_resolution",
            "recommended",
        ),
        _edge(
            "capability_resolution__capability_gap",
            "capability_resolution",
            "capability_gap",
            "failure",
        ),
        _edge(
            "capability_gap__capability_resolution",
            "capability_gap",
            "capability_resolution",
            "recovery",
        ),
        _resume("hypothesis_preregistration"),
        _resume("data_contract"),
    ]
    return {
        "schema_version": 1,
        "graph_id": "factor-research",
        "version": 1,
        "lifecycle": "active",
        "content_hash": "c" * 64,
        "entry_node": "hypothesis_preregistration",
        "nodes": nodes,
        "edges": edges,
    }


def _edge(edge_id: str, source: str, target: str, kind: str) -> dict:
    return {
        "edge_id": edge_id,
        "from_node": source,
        "to_node": target,
        "edge_type": kind,
        "guard": {},
        "required_evidence": [],
    }


def _resume(target: str) -> dict:
    edge = _edge(
        f"capability_resolution__resume_{target}",
        "capability_resolution",
        target,
        "recovery",
    )
    edge["guard"] = {"capability_detour_resume_node": target}
    return edge


def _advance(edge_id: str) -> dict:
    return advance_graph_branch(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        edge_id=edge_id,
        evidence={},
    )


def test_transition_keeps_detour_until_exact_resume(tmp_path, monkeypatch) -> None:
    path = tmp_path / "graph.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    initialize(path)
    with connect_sqlite(path) as conn:
        conn.execute(
            "UPDATE research_graph_versions SET graph_json=?",
            (orjson.dumps(_graph()).decode(),),
        )
        conn.execute(
            """
            UPDATE research_graph_branches
            SET current_node='hypothesis_preregistration', status='running'
            """
        )

    first = _advance("hypothesis__capability_resolution")
    assert first["capability_detour"]["status"] == "opened"
    assert first["report_container"]["anchor_node"] == (
        "hypothesis_preregistration"
    )
    _advance("capability_resolution__capability_gap")
    _advance("capability_gap__capability_resolution")

    context = build_graph_branch_context(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
    )
    assert context["capability_detour"]["resume_node"] == (
        "hypothesis_preregistration"
    )
    assert context["capability_detour"]["latest_trace_id"]
    assert context["report_container"]["kind"] == "special"
    with pytest.raises(ValueError, match="original interrupted node"):
        _advance("capability_resolution__resume_data_contract")

    resumed = _advance(
        "capability_resolution__resume_hypothesis_preregistration"
    )
    assert resumed["capability_detour"]["status"] == "resumed"
    assert resumed["current_node"] == "hypothesis_preregistration"
    final = build_graph_branch_context(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
    )
    assert "capability_detour" not in final
    assert final["report_container"] == {
        "kind": "chapter",
        "anchor_node": "hypothesis_preregistration",
    }
