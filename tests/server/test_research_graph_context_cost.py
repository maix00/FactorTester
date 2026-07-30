"""History-independent read-cost acceptance for local graph context."""

from __future__ import annotations

from copy import deepcopy
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
from server.services.research_graph.protocol import (
    MAX_AGENT_PACKET_BYTES,
    MAX_CAPABILITY_RESOLUTION_SUBMISSION_BYTES,
    MAX_AGENT_TRANSITION_BYTES,
    MAX_PERSISTED_TRACE_BYTES,
    MAX_TRANSITION_EVIDENCE_BYTES,
    serialize_agent_transition_evidence,
    serialize_capability_resolution_submission,
    serialize_bounded_trace_evidence,
)
from server.services.research_graph.packet_budget import (
    LEGACY_AGENT_PACKET_BYTES,
    graph_packet_budget,
    validate_graph_packet_budget,
)
from tests.server.data_contract_fixtures import initialize
from tests.server.data_contract_fixtures import checkpoint as data_checkpoint
from server.services.research_graph.research_cycle.replay import (
    validate_research_cycle_checkpoint,
)
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


def test_next_packet_uses_one_read_and_never_writes(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "next-cost.sqlite"
    initialize(path)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    research_graphs.build_graph_branch_next(
        instance_id="instance-1", branch_id="branch-1", owner="alice",
    )
    statements: list[str] = []
    real_connect = connect_sqlite

    def traced_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(branch_context, "connect_sqlite", traced_connect)
    before_bytes = _file_bytes(path)
    packet = research_graphs.build_graph_branch_next(
        instance_id="instance-1", branch_id="branch-1", owner="alice",
    )
    after_bytes = _file_bytes(path)
    normalized = [statement.lstrip().upper() for statement in statements]

    assert sum(item.startswith("SELECT ") for item in normalized) == 1
    assert not any(item.startswith((
        "INSERT ", "UPDATE ", "DELETE ", "REPLACE ",
    )) for item in normalized)
    assert before_bytes == after_bytes
    assert packet["next_bytes"] == len(orjson.dumps(packet))
    assert packet["next_bytes"] <= MAX_AGENT_PACKET_BYTES


def test_context_keeps_many_obligation_aliases_inside_agent_budget(
    tmp_path,
    monkeypatch,
) -> None:
    """A legitimate obligation set must not turn a context read into HTTP 500."""
    path = tmp_path / "many-obligations.sqlite"
    initialize(path, obligation_status="open")
    raw = deepcopy(data_checkpoint(obligation_status="open"))
    raw.pop("projection_hash", None)
    template = raw["obligations"][0]
    raw["obligations"] = []
    for index in range(16):
        obligation = deepcopy(template)
        obligation["obligation_id"] = f"obligation-data-{index}"
        obligation["epistemic_question"] = (
            f"义务 {index}：核验数据、因果时序、市场环境、执行成本与"
            "样本外边界是否足以支持当前研究决策。"
        )
        raw["obligations"].append(obligation)
    evidence = {
        "research_cycle_checkpoint": validate_research_cycle_checkpoint(raw),
        "evidence_refs": [],
    }
    refs = [f"evidence:{index}:" + "a" * 48 for index in range(8)]
    with connect_sqlite(path) as conn:
        conn.execute(
            "UPDATE research_graph_trace SET evidence_json=? "
            "WHERE trace_id='trace-bootstrap'",
            (orjson.dumps(evidence).decode(),),
        )
        conn.execute(
            "UPDATE research_graph_branches SET evidence_refs_json=? "
            "WHERE branch_id='branch-1'",
            (orjson.dumps(refs).decode(),),
        )

    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    context = research_graphs.build_graph_branch_context(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
    )

    assert context["context_bytes"] <= MAX_AGENT_PACKET_BYTES
    aliases = context["research_cycle"]["open_obligations"]
    assert len(aliases) == 16
    assert [item["obligation_id"] for item in aliases] == [
        f"obligation-data-{index}" for index in range(16)
    ]
    assert all(item["question_summary"] for item in aliases)
    assert all(item["detail_ref"] for item in aliases)


def test_context_transition_and_persisted_trace_have_distinct_budgets() -> None:
    legitimate_delta = {"research_note": "x" * 23_868}

    assert MAX_AGENT_PACKET_BYTES < MAX_AGENT_TRANSITION_BYTES
    assert MAX_AGENT_TRANSITION_BYTES == MAX_TRANSITION_EVIDENCE_BYTES
    assert MAX_TRANSITION_EVIDENCE_BYTES < MAX_PERSISTED_TRACE_BYTES
    serialized_delta = serialize_agent_transition_evidence(legitimate_delta)
    assert len(serialized_delta.encode()) > MAX_AGENT_PACKET_BYTES

    oversized_delta = {
        "research_note": "x" * MAX_TRANSITION_EVIDENCE_BYTES
    }
    with pytest.raises(
        ValueError,
        match=(
            "transition evidence transport exceeds "
            f"{MAX_TRANSITION_EVIDENCE_BYTES}"
        ),
    ):
        serialize_agent_transition_evidence(oversized_delta)

    audit_payload = {
        "research_note": "x" * (MAX_TRANSITION_EVIDENCE_BYTES + 1)
    }
    serialized_trace = serialize_bounded_trace_evidence(audit_payload)
    assert len(serialized_trace.encode()) > MAX_AGENT_PACKET_BYTES
    assert len(serialized_trace.encode()) < MAX_PERSISTED_TRACE_BYTES


def test_graph_packet_budget_is_calibrated_per_version() -> None:
    legacy = graph_packet_budget({})
    assert legacy["policy_ref"] == "agent-packet-budget@legacy"
    assert legacy["ceiling_bytes"] == LEGACY_AGENT_PACKET_BYTES
    assert legacy["calibration_status"] == "legacy_schema_exempt"
    assert legacy["budget_scope"] == "graph_legacy"
    assert len(legacy["profile_hash"]) == 64
    assert graph_packet_budget({"schema_version": 2})[
        "calibration_status"
    ] == "uncalibrated"
    assert graph_packet_budget({"schema_version": 2})[
        "budget_scope"
    ] == "runtime_profile"
    assert len(graph_packet_budget({"schema_version": 2})["profile_hash"]) == 64

    calibrated = validate_graph_packet_budget({
        "schema_version": 1,
        "policy_ref": "agent-packet-budget@factor-research-v9",
        "ceiling_bytes": 6400,
        "observed_max_packet_bytes": 5800,
        "sample_count": 2,
        "sampled_anchor_refs": [
            "node:factor_semantics",
            "node:validation_design",
        ],
        "activation_measurements": [
            "provider_actual_token_comparison",
            "server_packet_latency",
        ],
    })

    assert calibrated["ceiling_bytes"] == 6400
    assert calibrated["headroom_bytes"] == 600
    assert calibrated["calibration_status"] == "graph_version_calibrated"


def test_graph_packet_budget_rejects_magic_limit_without_headroom() -> None:
    with pytest.raises(
        ValueError,
        match="lacks calibrated semantic headroom",
    ):
        validate_graph_packet_budget({
            "schema_version": 1,
            "ceiling_bytes": 6000,
            "observed_max_packet_bytes": 5700,
            "sample_count": 1,
            "sampled_anchor_refs": ["node:validation_design"],
            "activation_measurements": [
                "provider_actual_token_comparison",
                "server_packet_latency",
            ],
        })


def test_target_resolution_does_not_consume_agent_delta_budget() -> None:
    payload = {
        "research_note": "x" * 5_900,
        "target_capability_resolution": {
            "node_id": "validation_design",
            "bindings": [{"capability_description": "y" * 1_000}],
        },
    }

    serialized = serialize_agent_transition_evidence(payload)

    assert len(serialized.encode()) <= MAX_AGENT_TRANSITION_BYTES
    assert "target_capability_resolution" not in orjson.loads(serialized)


def test_target_resolution_has_an_independent_hard_budget() -> None:
    payload = {"bindings": [{"capability_description": "x" * 4_096}]}

    with pytest.raises(
        ValueError,
        match=(
            "capability resolution submission exceeds "
            f"{MAX_CAPABILITY_RESOLUTION_SUBMISSION_BYTES}"
        ),
    ):
        serialize_capability_resolution_submission(payload)


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
    assert sum("SEARCH " in detail for detail in details) == 5
    assert any("RESEARCH_GRAPH_INSTANCES" in detail for detail in details)
    assert any("RESEARCH_GRAPH_BRANCHES" in detail for detail in details)
    assert any("RESEARCH_GRAPH_TRACE" in detail for detail in details)
    assert any("RESEARCH_WORK_PACKAGES" in detail for detail in details)
    assert any(
        "IDX_REPORT_ITEM_CHECKPOINTS_BRANCH_NODE" in detail
        for detail in details
    )


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
