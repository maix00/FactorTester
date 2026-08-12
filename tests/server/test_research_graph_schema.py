from __future__ import annotations

import settings as Settings
from server.services import agent_flow, research_graphs
from server.services.research_graph import schema as graph_schema
from tools.data.sqlite.db import connect_sqlite


def test_startup_migrates_work_package_title_column(tmp_path, monkeypatch):
    """Old lifecycle stores must remain readable by profile research routes."""
    path = tmp_path / "research-graph.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    agent_flow.clear_store_cache()

    with connect_sqlite(path) as conn:
        graph_schema.create_schema(conn)
        conn.execute(
            "ALTER TABLE research_work_packages DROP COLUMN title"
        )

    research_graphs.ensure_schema()

    with connect_sqlite(path) as conn:
        columns = {
            str(row["name"])
            for row in conn.execute(
                "PRAGMA table_info(research_work_packages)"
            )
        }
    assert "title" in columns
