from __future__ import annotations

import json

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
        "graph_id": "factor-research",
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
            "entry_evidence": ["hypothesis-note"],
            "exit_evidence": [],
        }],
        "edges": [],
        "provenance": {"source": "test"},
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


def test_yaml_download_is_validated_and_content_addressed(client) -> None:
    stored = research_graphs.register_graph(_graph(), actor="curator-agent")
    path = "/api/research-graphs/factor-research/versions/1/yaml"

    response = client.get(path)

    assert response.status_code == 200
    assert response.content_type.startswith("application/yaml")
    assert response.headers["X-FactorTester-Graph-Version"] == "1"
    assert response.headers["X-FactorTester-Graph-Content-Hash"] == stored["content_hash"]
    assert response.headers["ETag"] == f'"{stored["content_hash"]}"'
    assert response.headers["Cache-Control"] == "public, max-age=31536000, immutable"
    assert 'factor-research-v1.yaml"' in response.headers["Content-Disposition"]
    assert response.headers["Content-Disposition"].endswith(".yaml\"")

    payload = yaml.safe_load(response.data.decode("utf-8"))
    assert payload == research_graphs.graph_definition(stored)
    assert "created_by" not in payload
    assert "created_at" not in payload
    assert json.dumps(payload, ensure_ascii=False, sort_keys=True)

    not_modified = client.get(path, headers={"If-None-Match": response.headers["ETag"]})
    assert not_modified.status_code == 304
    assert not_modified.data == b""


def test_yaml_download_accepts_the_public_graph_gateway_session(client) -> None:
    research_graphs.register_graph(_graph(), actor="curator-agent")
    with client.session_transaction() as session:
        session.pop("username", None)
        session["manager_gateway_public_graph"] = True

    response = client.get(
        "/api/research-graphs/factor-research/versions/1/yaml"
    )

    assert response.status_code == 200
    assert response.content_type.startswith("application/yaml")
