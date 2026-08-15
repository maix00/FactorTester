from __future__ import annotations

import json

from flask import Flask
import pytest
import yaml

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
        "nodes": [
            {
                "node_id": "hypothesis",
                "kind": "research",
                "purpose": "freeze hypothesis",
                "enforcement": "audited",
                "required_capabilities": [],
                "entry_evidence": [],
                "exit_evidence": ["hypothesis-note"],
            },
            {
                "node_id": "decision",
                "kind": "research",
                "purpose": "record decision",
                "enforcement": "audited",
                "required_capabilities": [],
                "entry_evidence": [],
                "exit_evidence": [],
            },
        ],
        "edges": [
            {
                "edge_id": "hypothesis__decision",
                "from_node": "hypothesis",
                "to_node": "decision",
                "edge_type": "recommended",
                "guard": {},
                "required_evidence": [],
                "risk_level": "L1",
                "counterexamples": [],
            },
        ],
        "provenance": {"source": "test"},
    }
    graph["content_hash"] = graph_content_hash(graph)
    return graph


def _presentation(graph: dict, *, locale: str, title: str = "Research graph") -> dict:
    return {
        "schema_version": 1,
        "graph_id": graph["graph_id"],
        "version": graph["version"],
        "content_hash": graph["content_hash"],
        "locale": locale,
        "title": title,
        "description": "Server-managed graph presentation",
        "nodes": {
            "hypothesis": {
                "label": "Hypothesis",
                "purpose": "Freeze the hypothesis",
                "entry_evidence": [],
                "exit_evidence": ["Hypothesis note"],
            },
            "decision": {
                "label": "Decision",
                "purpose": "Record the decision",
            },
        },
        "edges": {
            "hypothesis__decision": {
                "label": "Recommended",
                "description": "The recommended research transition",
            },
        },
        "capability_descriptions": {},
    }


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


def test_presentation_is_a_separate_immutable_revision(tmp_path, monkeypatch):
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "graphs.sqlite")
    research_graphs.ensure_schema()
    graph = research_graphs.register_graph(_graph(), actor="curator-agent")

    first = research_graphs.register_presentation(
        graph,
        _presentation(graph, locale="en"),
        actor="curator-agent",
    )
    same = research_graphs.register_presentation(
        graph,
        _presentation(graph, locale="en"),
        actor="another-curator",
    )
    second = research_graphs.register_presentation(
        graph,
        _presentation(graph, locale="en", title="Research graph v2"),
        actor="curator-agent",
    )

    assert first["translation_revision"] == 1
    assert same["translation_revision"] == 1
    assert same["created_by"] == "curator-agent"
    assert second["translation_revision"] == 2
    assert second["translation_hash"] != first["translation_hash"]
    assert graph["content_hash"] == _graph()["content_hash"]


def test_locale_projection_does_not_change_graph_hash(tmp_path, monkeypatch):
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "graphs.sqlite")
    research_graphs.ensure_schema()
    graph = research_graphs.register_graph(_graph(), actor="curator-agent")
    research_graphs.register_presentation(
        graph,
        _presentation(graph, locale="en"),
        actor="curator-agent",
    )

    localized = research_graphs.list_graph_versions(
        graph_id="factor-research",
        locale="en",
    )[0]

    assert localized["content_hash"] == graph["content_hash"]
    assert localized["presentation_status"] == "available"
    assert localized["presentation"]["title"] == "Research graph"
    assert research_graphs.list_graph_versions(
        graph_id="factor-research",
        locale="zh-Hans",
    )[0]["presentation_status"] == "missing"


def test_locale_yaml_is_a_bundle_and_missing_locale_is_explicit(client):
    graph = research_graphs.register_graph(_graph(), actor="curator-agent")
    presentation = research_graphs.register_presentation(
        graph,
        _presentation(graph, locale="en"),
        actor="curator-agent",
    )

    versions = client.get(
        "/api/research-graphs/factor-research/versions?locale=en"
    )
    assert versions.status_code == 200
    assert versions.json["locale"] == "en"
    assert versions.json["versions"][0]["presentation_status"] == "available"
    assert versions.json["versions"][0]["presentation"]["title"] == (
        "Research graph"
    )

    response = client.get(
        "/api/research-graphs/factor-research/versions/1/yaml?locale=en"
    )

    assert response.status_code == 200
    assert response.headers["Content-Language"] == "en"
    assert response.headers["X-FactorTester-Graph-Locale"] == "en"
    assert response.headers["X-FactorTester-Graph-Translation-Hash"] == (
        presentation["translation_hash"]
    )
    assert f"-en-{presentation['translation_hash'][:16]}.yaml" in response.headers[
        "Content-Disposition"
    ]
    payload = yaml.safe_load(response.data.decode())
    assert payload["format"] == "factor-tester.research-graph-presentation.v1"
    assert payload["graph"]["content_hash"] == graph["content_hash"]
    assert payload["presentation"]["locale"] == "en"
    assert "created_by" not in payload["presentation"]
    assert json.dumps(payload, ensure_ascii=False, sort_keys=True)

    missing = client.get(
        "/api/research-graphs/factor-research/versions/1/yaml?locale=zh-Hans"
    )
    assert missing.status_code == 409
    assert missing.json["locale"] == "zh-Hans"


def test_presentation_validation_requires_exact_graph_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "graphs.sqlite")
    research_graphs.ensure_schema()
    graph = research_graphs.register_graph(_graph(), actor="curator-agent")
    invalid = _presentation(graph, locale="en")
    invalid["nodes"].pop("decision")

    with pytest.raises(ValueError, match="missing decision"):
        research_graphs.register_presentation(
            graph,
            invalid,
            actor="curator-agent",
        )
