from __future__ import annotations

from copy import deepcopy

import pytest

import settings as Settings
from cli_anything.factortester_research.core.graph import graph_content_hash
from server.services import research_graphs
from server.services import research_runs
from server.services.research_graph.branch.runtime import (
    create_graph_instance,
)


def _graph(*, version: int = 2) -> dict:
    graph = {
        "schema_version": 1,
        "graph_id": "factor-research",
        "version": version,
        "parent_version": version - 1,
        "lifecycle": "draft",
        "research_semantics": "product_neutral",
        "entry_node": "hypothesis",
        "nodes": [{
            "node_id": "hypothesis",
            "kind": "research",
            "purpose": "freeze one hypothesis",
            "enforcement": "deterministic",
            "required_capabilities": [],
            "conditional_capabilities": [],
        }],
        "edges": [],
        "capability_descriptors": {},
        "provenance": {"source": "test"},
    }
    graph["content_hash"] = graph_content_hash(graph)
    return graph


def _revision(original: dict, *, purpose: str = "freeze exactly one hypothesis"):
    graph = deepcopy(original)
    graph["nodes"][0]["purpose"] = purpose
    graph["change_manifest"] = {
        "draft_revision": {
            "replaces_content_hash": original["content_hash"],
            "reason_code": "independent_review",
        },
    }
    graph["content_hash"] = graph_content_hash(graph)
    return graph


@pytest.fixture
def graph_db(tmp_path, monkeypatch):
    path = tmp_path / "graph.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    research_graphs.ensure_schema()
    yield path


def test_unused_draft_revision_is_atomic_auditable_and_idempotent(
    graph_db,
) -> None:
    original = research_graphs.register_graph(_graph(), actor="curator")
    revised = _revision(original)

    stored = research_graphs.revise_unused_draft(
        revised,
        actor="server-maintenance-agent",
    )
    repeated = research_graphs.revise_unused_draft(
        revised,
        actor="server-maintenance-agent",
    )

    assert stored["content_hash"] == revised["content_hash"]
    assert repeated["content_hash"] == revised["content_hash"]
    assert stored["change_manifest"]["draft_revision"][
        "replaces_content_hash"
    ] == original["content_hash"]
    assert research_graphs.load_graph(
        graph_id="factor-research",
        version=2,
    )["content_hash"] == revised["content_hash"]


def test_draft_revision_rejects_a_wrong_source_hash(graph_db) -> None:
    original = research_graphs.register_graph(_graph(), actor="curator")
    revised = _revision(original)
    revised["change_manifest"]["draft_revision"][
        "replaces_content_hash"
    ] = "a" * 64
    revised["content_hash"] = graph_content_hash(revised)

    with pytest.raises(ValueError, match="source hash"):
        research_graphs.revise_unused_draft(revised, actor="server-agent")


def test_draft_revision_rejects_an_instantiated_graph(graph_db) -> None:
    original = research_graphs.register_graph(_graph(), actor="curator")
    run = research_runs.create_run(
        owner="alice",
        workspace_id="workspace-1",
        configuration_id="shadow-config",
        configuration_revision=1,
        run_spec={"workspace_id": "workspace-1", "factor": "test"},
    )
    create_graph_instance(
        graph_id="factor-research",
        owner="alice",
        product_group="equities",
        workspace_id="workspace-1",
        shadow_graph_version=2,
        shadow_run_id=run["run_id"],
        capability_resolution={
            "node_id": "hypothesis",
            "bindings": [],
            "gaps": [],
            "triggered_conditional_bindings": [],
            "undetermined_conditions": [],
        },
    )

    with pytest.raises(ValueError, match="immutable after"):
        research_graphs.revise_unused_draft(
            _revision(original),
            actor="server-agent",
        )
