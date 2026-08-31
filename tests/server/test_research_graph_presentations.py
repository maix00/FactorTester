from __future__ import annotations

import json

import pytest
from flask import Flask

import settings as Settings
from server.modules.single_factor_test import sft_bp
from server.services import research_graphs
from server.services.research_graph.presentations import create_schema
from server.services.research_graph.protocol import graph_content_hash
from tools.data.sqlite.db import connect_sqlite


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


def test_presentation_is_the_current_locale_overlay(tmp_path, monkeypatch):
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

    assert "translation_revision" not in first
    assert "translation_hash" not in first
    assert same["created_by"] == "another-curator"
    assert second["created_by"] == "curator-agent"
    assert second["title"] == "Research graph v2"
    assert research_graphs.load_presentation(
        graph_id="factor-research", version=1, locale="en"
    )["title"] == "Research graph v2"
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


def test_presentation_validation_allows_partial_overlay_and_rejects_unknown_fields(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "graphs.sqlite")
    research_graphs.ensure_schema()
    graph = research_graphs.register_graph(_graph(), actor="curator-agent")
    partial = _presentation(graph, locale="en")
    partial["nodes"].pop("decision")
    stored = research_graphs.register_presentation(
        graph,
        partial,
        actor="curator-agent",
    )
    assert "decision" not in stored["nodes"]

    invalid = _presentation(graph, locale="en")
    invalid["nodes"]["decision"]["unexpected"] = "not allowed"
    # The unknown-field check is intentionally independent from Graph node
    # coverage; partial overlays are valid, malformed entries are not.
    with pytest.raises(ValueError, match="unknown fields"):
        research_graphs.register_presentation(
            graph,
            invalid,
            actor="curator-agent",
        )


def test_old_translation_history_is_collapsed_without_hash_metadata(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "graphs.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", db_path)
    with connect_sqlite(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE research_graph_presentations (
                graph_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                locale TEXT NOT NULL,
                translation_revision INTEGER NOT NULL,
                translation_hash TEXT NOT NULL,
                presentation_json TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY (graph_id, version, locale, translation_revision)
            )
            """
        )
        for revision, title in ((1, "old"), (2, "current")):
            conn.execute(
                """
                INSERT INTO research_graph_presentations VALUES
                    (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "factor-research", 1, "en", revision,
                    f"hash-{revision}",
                    json.dumps({
                        "schema_version": 1,
                        "graph_id": "factor-research",
                        "version": 1,
                        "content_hash": "legacy-graph-hash",
                        "locale": "en",
                        "title": title,
                        "nodes": {},
                        "edges": {},
                        "capability_descriptions": {},
                    }),
                    "curator",
                    float(revision),
                ),
            )
        create_schema(conn)
        columns = {
            str(row["name"])
            for row in conn.execute(
                "PRAGMA table_info(research_graph_presentations)"
            ).fetchall()
        }
        stored = conn.execute(
            "SELECT * FROM research_graph_presentations"
        ).fetchone()

    assert "translation_revision" not in columns
    assert "translation_hash" not in columns
    assert stored["locale"] == "en"
    assert json.loads(stored["presentation_json"])["title"] == "current"
    assert "content_hash" not in json.loads(stored["presentation_json"])
