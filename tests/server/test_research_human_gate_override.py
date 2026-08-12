from __future__ import annotations

import sqlite3

from server.services.research_graph.branch.human_gate_override import (
    current_override,
    set_override,
)


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def test_override_is_scoped_to_exact_node_and_checkpoint() -> None:
    conn = _connection()
    saved = set_override(
        conn,
        owner="max",
        instance_id="research",
        branch_id="main",
        node_id="data_contract",
        checkpoint_ref="trace:one",
        enabled=True,
    )
    assert saved["enabled"] is True

    current = current_override(
        conn,
        owner="max",
        instance_id="research",
        branch_id="main",
        node_id="data_contract",
        checkpoint_ref="trace:one",
    )
    assert current["enabled"] is True
    assert current["scope"] == "missing_coverage_only"

    stale = current_override(
        conn,
        owner="max",
        instance_id="research",
        branch_id="main",
        node_id="factor_semantics",
        checkpoint_ref="trace:two",
    )
    assert stale["enabled"] is False
    assert stale["stale"] is True
