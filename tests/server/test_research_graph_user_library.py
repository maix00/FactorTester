from __future__ import annotations

import pytest
import yaml
from flask import Flask

import settings as Settings
from server.modules.single_factor_test import sft_bp
from server.services import research_graphs
from server.services.research_graph.protocol import graph_content_hash


def _graph() -> dict:
    graph = {
        "schema_version": 1,
        "graph_id": "personal-research",
        "version": 1,
        "lifecycle": "observed",
        "parent_version": 0,
        "research_semantics": "product_neutral",
        "nodes": [{
            "node_id": "hypothesis",
            "kind": "research",
            "purpose": "freeze hypothesis",
            "enforcement": "audited",
            "required_capabilities": [],
            "entry_evidence": [],
            "exit_evidence": [],
        }],
        "edges": [],
        "provenance": {"source": "user"},
    }
    graph["content_hash"] = graph_content_hash(graph)
    return graph


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "graphs.sqlite")
    research_graphs.ensure_schema()
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "alice"
    return client


def test_user_graph_files_are_local_and_owner_scoped(tmp_path, monkeypatch):
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "graphs.sqlite")
    research_graphs.ensure_schema()
    graph = _graph()
    raw = yaml.safe_dump(graph, allow_unicode=True).encode()

    first = research_graphs.upload_user_graph(
        owner="alice",
        filename="my-graph.yaml",
        raw_yaml=raw,
        name="My graph",
    )

    assert first["name"] == "My graph"
    assert first["sync_scope"] == "manager-local"
    assert research_graphs.list_user_graphs(owner="bob") == []
    assert research_graphs.list_user_graphs(owner="alice")[0]["graph_file_id"] == (
        first["graph_file_id"]
    )

    selected = research_graphs.set_default_user_graph(
        owner="alice",
        kind="user",
        graph_file_id=first["graph_file_id"],
    )
    assert selected is not None
    assert selected["kind"] == "user"
    assert selected["file"]["graph"]["graph_id"] == "personal-research"
    assert research_graphs.list_user_graphs(owner="alice")[0]["is_default"]

    assert research_graphs.delete_user_graph(
        owner="bob", graph_file_id=first["graph_file_id"]
    ) is False
    assert research_graphs.delete_user_graph(
        owner="alice", graph_file_id=first["graph_file_id"]
    ) is True
    assert research_graphs.get_default_user_graph(owner="alice") is None


def test_user_graph_upload_recomputes_one_stale_semantic_hash(tmp_path, monkeypatch):
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "graphs.sqlite")
    research_graphs.ensure_schema()
    graph = _graph()
    graph["content_hash"] = "stale"
    graph["locale"] = "en"

    stored = research_graphs.upload_user_graph(
        owner="alice",
        filename="stale.yml",
        raw_yaml=yaml.safe_dump(graph),
    )
    loaded = research_graphs.load_user_graph(
        owner="alice", graph_file_id=stored["graph_file_id"]
    )

    assert loaded is not None
    assert loaded["graph"]["content_hash"] == graph_content_hash({
        key: value
        for key, value in graph.items()
        if key not in {"content_hash", "locale"}
    })
    assert "content_hash: stale" not in loaded["yaml"]
    assert "locale" not in loaded["graph"]
    assert "locale:" not in loaded["yaml"]


def test_federation_only_forwards_graph_runtime_instances():
    from server.manager.http.federation.service_proxy import (
        FederationServiceProxyRoutesMixin,
    )

    assert not FederationServiceProxyRoutesMixin._federation_path_allowed(
        "/api/research-graphs/user-library"
    )
    assert not FederationServiceProxyRoutesMixin._federation_path_allowed(
        "/api/research-graphs/factor-research/versions"
    )
    assert FederationServiceProxyRoutesMixin._federation_path_allowed(
        "/api/research-graph-instances/instance-1/branches/branch-1"
    )


def test_federation_forwards_only_registered_backtest_analysis_routes():
    from server.manager.http.federation.service_proxy import (
        FederationServiceProxyRoutesMixin,
    )

    for path in (
        "/get_group_detail",
        "/get_group_ranking_detail",
        "/get_group_snapshot",
        "/get_group_order_flow",
    ):
        assert FederationServiceProxyRoutesMixin._federation_path_allowed(path)

    assert not FederationServiceProxyRoutesMixin._federation_path_allowed(
        "/get_unregistered_analysis"
    )
