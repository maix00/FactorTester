"""Final Graph and AgentFlow owner-schema acceptance tests."""

from __future__ import annotations

import pytest

import settings as Settings
from server.services import agent_flow, research_graphs
from server.services.research_graph.schema import (
    GRAPH_OWNER_TABLES,
    final_schema_report,
)
from tools.data.sqlite.db import connect_sqlite


def _tables(path) -> set[str]:
    with connect_sqlite(path) as conn:
        return {
            str(row["name"])
            for row in conn.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
                """
            ).fetchall()
        }


def _initialize(tmp_path, monkeypatch):
    graph_path = tmp_path / "graph.sqlite"
    flow_path = tmp_path / "agent-flow.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", graph_path)
    monkeypatch.setenv("AGENT_FLOW_DB_PATH", str(flow_path))
    agent_flow.clear_store_cache()
    research_graphs.ensure_schema()
    return graph_path, flow_path


def test_fresh_schema_has_exact_seven_graph_and_two_agent_flow_owners(
    tmp_path,
    monkeypatch,
) -> None:
    graph_path, flow_path = _initialize(tmp_path, monkeypatch)

    assert _tables(graph_path) == set(GRAPH_OWNER_TABLES)
    assert _tables(flow_path) == {
        "agent_budget_periods",
        "agent_invocations",
    }
    with connect_sqlite(graph_path) as conn:
        assert final_schema_report(conn) == {
            "graph_owner_tables": sorted(GRAPH_OWNER_TABLES),
            "legacy_graph_tables": [],
            "owner_count": 7,
            "is_final": True,
        }


def test_warm_schema_check_is_one_read_with_no_ddl_or_pragma(
    tmp_path,
    monkeypatch,
) -> None:
    graph_path, _ = _initialize(tmp_path, monkeypatch)
    statements: list[str] = []

    def traced_connect(*args, **kwargs):
        conn = connect_sqlite(*args, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(
        "server.services.research_graph.schema.connect_sqlite",
        traced_connect,
    )
    research_graphs.ensure_schema()
    normalized = [" ".join(item.upper().split()) for item in statements]

    assert len([item for item in normalized if item.startswith("SELECT")]) == 1
    assert not any(
        item.startswith(("CREATE", "ALTER", "DROP", "PRAGMA"))
        for item in normalized
    )
    assert _tables(graph_path) == set(GRAPH_OWNER_TABLES)


def test_legacy_owner_blocks_startup_without_mutating_database(
    tmp_path,
    monkeypatch,
) -> None:
    graph_path, _ = _initialize(tmp_path, monkeypatch)
    with connect_sqlite(graph_path) as conn:
        conn.execute(
            "CREATE TABLE research_graph_reviews (review_id TEXT PRIMARY KEY)"
        )
    before = _tables(graph_path)

    with pytest.raises(RuntimeError, match="explicit offline cutover"):
        research_graphs.ensure_schema()

    assert _tables(graph_path) == before
