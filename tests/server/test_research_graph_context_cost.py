"""History-independent read-cost acceptance for local graph context."""

from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
import time

import orjson
import pytest

import settings as Settings
from server.services import research_graphs
from server.services.research_graph.branch import context as branch_context
from server.services.research_graph.branch.repository import (
    CURRENT_BRANCH_CONTEXT_SQL,
)
from tests.server.data_contract_fixtures import initialize
from tools.data.sqlite.db import connect_sqlite


def _file_bytes(path: Path) -> tuple[int, int]:
    wal = Path(str(path) + "-wal")
    return (
        path.stat().st_size if path.exists() else 0,
        wal.stat().st_size if wal.exists() else 0,
    )


def _measure_context(
    path: Path,
    monkeypatch,
    *,
    history_rows: int,
) -> dict:
    initialize(path)
    with connect_sqlite(path) as conn:
        conn.executemany(
            """
            INSERT INTO research_graph_trace (
                trace_id, instance_id, branch_id, edge_id, from_node, to_node,
                evidence_json, telemetry_json, actor, created_at
            ) VALUES (?, 'instance-1', 'branch-1', 'historical-only',
                      'x', 'x', '{}', '{}', 'fixture', ?)
            """,
            [
                (f"historical-{index}", float(index + 10))
                for index in range(history_rows)
            ],
        )
    statements: list[str] = []
    real_connect = connect_sqlite

    def traced_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    research_graphs.build_graph_branch_context(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
    )
    monkeypatch.setattr(branch_context, "connect_sqlite", traced_connect)
    before_bytes = _file_bytes(path)
    started = time.perf_counter()
    context = research_graphs.build_graph_branch_context(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    after_bytes = _file_bytes(path)
    normalized = [
        statement.lstrip().upper() for statement in statements
    ]
    return {
        "context": context,
        "elapsed_ms": elapsed_ms,
        "selects": [
            item for item in normalized if item.startswith("SELECT ")
        ],
        "writes": [
            item for item in normalized
            if item.startswith(("INSERT ", "UPDATE ", "DELETE ", "REPLACE "))
        ],
        "transactions": [
            item for item in normalized
            if item.startswith(("BEGIN", "COMMIT", "ROLLBACK"))
        ],
        "before_bytes": before_bytes,
        "after_bytes": after_bytes,
    }


def test_context_cost_is_constant_for_empty_and_large_history(
    tmp_path,
    monkeypatch,
) -> None:
    small = _measure_context(
        tmp_path / "small.sqlite",
        monkeypatch,
        history_rows=0,
    )
    large = _measure_context(
        tmp_path / "large.sqlite",
        monkeypatch,
        history_rows=1000,
    )

    for measurement in (small, large):
        assert len(measurement["selects"]) == 1
        assert measurement["writes"] == []
        assert measurement["transactions"] == []
        assert measurement["before_bytes"] == measurement["after_bytes"]
        assert measurement["elapsed_ms"] < 500
        assert measurement["context"]["context_bytes"] <= 6000
    assert small["selects"] == large["selects"]
    assert small["context"] == large["context"]


def test_context_query_plan_uses_primary_key_lookups(
    tmp_path,
) -> None:
    path = tmp_path / "query-plan.sqlite"
    initialize(path)

    with connect_sqlite(path) as conn:
        plan = conn.execute(
            "EXPLAIN QUERY PLAN " + CURRENT_BRANCH_CONTEXT_SQL,
            ("instance-1", "branch-1", "alice"),
        ).fetchall()

    details = [str(row["detail"]).upper() for row in plan]
    assert not any("SCAN " in detail for detail in details)
    assert sum("SEARCH " in detail for detail in details) == 3
    assert any("RESEARCH_GRAPH_INSTANCES" in detail for detail in details)
    assert any("RESEARCH_GRAPH_BRANCHES" in detail for detail in details)
    assert any("RESEARCH_GRAPH_TRACE" in detail for detail in details)


def test_context_request_closes_its_sqlite_connection(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "connection-lifetime.sqlite"
    initialize(path)
    connections: list[sqlite3.Connection] = []

    def tracked_connect(*args, **kwargs):
        connection = connect_sqlite(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    monkeypatch.setattr(branch_context, "connect_sqlite", tracked_connect)
    research_graphs.build_graph_branch_context(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
    )

    assert len(connections) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connections[0].execute("SELECT 1")


def test_context_cost_receipt_is_content_addressed() -> None:
    receipt_path = (
        Path(__file__).parents[2]
        / "docs"
        / "research-decision-graph"
        / "acceptance"
        / "context-cost-receipt.json"
    )
    receipt = orjson.loads(receipt_path.read_bytes())
    declared_hash = receipt.pop("receipt_hash")
    actual_hash = hashlib.sha256(
        orjson.dumps(receipt, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()

    assert actual_hash == declared_hash
    assert receipt["comparisons"] == {
        "sql_equal": True,
        "context_equal": True,
    }
    assert {
        item["history_rows"] for item in receipt["measurements"]
    } == {0, 1000}
