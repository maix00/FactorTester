"""Server-owned availability evidence on the existing data-contract edge."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import orjson
import pytest

import settings as Settings
from server.services.research_graph.branch import (
    data_contract as data_contract_service,
)
from server.services.research_graph.branch.transition import (
    advance_graph_branch,
)
from tests.server.data_contract_fixtures import (
    initialize,
    profile,
    transition_evidence,
)
from tools.data.availability.model import profile_document
from tools.data.sqlite.db import connect_sqlite


def test_data_contract_edge_projects_server_evidence_outside_write_lock(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "graphs.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    initialize(path)

    def availability(**kwargs):
        assert kwargs == {
            "product_names": ["A.DCE"],
            "source_names": ["Local"],
            "probe": False,
            "expanded": False,
        }
        with sqlite3.connect(path, timeout=0.05) as other:
            other.execute("BEGIN IMMEDIATE")
            other.rollback()
        return profile()

    monkeypatch.setattr(
        data_contract_service,
        "availability_for_scope",
        availability,
    )

    result = advance_graph_branch(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        edge_id="data_contract__factor_semantics",
        evidence=transition_evidence(),
    )

    assert result["current_node"] == "factor_semantics"
    with connect_sqlite(path) as conn:
        row = conn.execute(
            """
            SELECT evidence_json FROM research_graph_trace
            WHERE trace_id=(SELECT latest_trace_id
                            FROM research_graph_branches
                            WHERE branch_id='branch-1')
            """
        ).fetchone()
    trace = orjson.loads(row["evidence_json"])
    assert "data_availability_request" not in trace
    envelope = trace["server_evidence"]["data_availability"]
    assert envelope["evidence_kind"] == "data_availability"
    assert envelope["identity_refs"] == {
        "contract_hash": "1" * 64,
        "methodology_hash": "2" * 64,
    }
    assert envelope["facts"]["profile_ref"] == (
        "data-availability-profile:" + profile()["profile_hash"]
    )
    assert envelope["facts"]["request"] == {
        "products": ["A.DCE"],
        "sources": ["Local"],
        "probe": False,
        "expanded": False,
    }
    assert envelope["facts"]["product_status"] == [{
        "product": "A.DCE",
        "available": True,
    }]
    assert "profile" not in envelope["facts"]
    assert envelope["facts"]["requested_product_availability_present"] is True
    assert trace["evidence_refs"] == [
        "evidence:" + envelope["envelope_hash"]
    ]


def test_data_contract_trace_stays_bounded_for_multi_product_profile(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "graphs.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    initialize(path)
    products = [f"P{index}.DCE" for index in range(20)]
    large_profile = profile_document(
        product_scope=products,
        source_scope=["Local"],
        probe=False,
        expanded=False,
        entries=[
            {
                "product": product,
                "source": f"LocalCNFutures{frequency}",
                "mode": "historical_snapshot",
                "status": "available",
                "frequency": frequency,
                "replayable": True,
                "point_in_time": False,
                "coverage": {
                    "start": "2010-01-01T00:00:00+00:00",
                    "end": "2026-07-20T00:00:00+00:00",
                    "rows": 1_000_000,
                },
            }
            for product in products
            for frequency in ("MIN1", "DAY1", "CONTRACT_MIN1")
        ],
        as_of=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        data_contract_service,
        "availability_for_scope",
        lambda **_kwargs: large_profile,
    )
    payload = transition_evidence()
    payload["data_availability_request"]["products"] = products

    result = advance_graph_branch(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        edge_id="data_contract__factor_semantics",
        evidence=payload,
    )

    assert result["current_node"] == "factor_semantics"
    with connect_sqlite(path) as conn:
        row = conn.execute(
            """
            SELECT evidence_json FROM research_graph_trace
            WHERE trace_id=(SELECT latest_trace_id
                            FROM research_graph_branches
                            WHERE branch_id='branch-1')
            """
        ).fetchone()
    assert len(row["evidence_json"].encode()) <= 6000


def test_client_cannot_submit_server_evidence(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "graphs.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    initialize(path)
    payload = transition_evidence()
    payload["server_evidence"] = {"data_availability": {"forged": True}}

    with pytest.raises(ValueError, match="server_evidence"):
        advance_graph_branch(
            instance_id="instance-1",
            branch_id="branch-1",
            owner="alice",
            edge_id="data_contract__factor_semantics",
            evidence=payload,
        )


def test_unavailable_requested_product_cannot_advance(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "graphs.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    initialize(path)
    monkeypatch.setattr(
        data_contract_service,
        "availability_for_scope",
        lambda **_kwargs: profile(status="unavailable"),
    )

    with pytest.raises(
        ValueError,
        match="requested_product_availability_present",
    ):
        advance_graph_branch(
            instance_id="instance-1",
            branch_id="branch-1",
            owner="alice",
            edge_id="data_contract__factor_semantics",
            evidence=transition_evidence(),
        )

    with connect_sqlite(path) as conn:
        row = conn.execute(
            """
            SELECT current_node, latest_trace_id
            FROM research_graph_branches WHERE branch_id='branch-1'
            """
        ).fetchone()
    assert tuple(row) == ("data_contract", "trace-bootstrap")


def test_preflight_rejects_a_concurrent_branch_change(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "graphs.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    initialize(path)

    def availability(**_kwargs):
        with connect_sqlite(path) as conn:
            conn.execute(
                """
                INSERT INTO research_graph_trace (
                    trace_id, instance_id, branch_id, edge_id,
                    from_node, to_node, evidence_json, telemetry_json,
                    actor, created_at
                ) VALUES (
                    'trace-race', 'instance-1', 'branch-1', 'concurrent',
                    'data_contract', 'data_contract', '{}', '{}', 'alice', 2
                )
                """
            )
            conn.execute(
                """
                UPDATE research_graph_branches
                SET latest_trace_id='trace-race', updated_at=2
                WHERE branch_id='branch-1'
                """
            )
        return profile()

    monkeypatch.setattr(
        data_contract_service,
        "availability_for_scope",
        availability,
    )
    with pytest.raises(ValueError, match="preflight is stale"):
        advance_graph_branch(
            instance_id="instance-1",
            branch_id="branch-1",
            owner="alice",
            edge_id="data_contract__factor_semantics",
            evidence=transition_evidence(),
        )

    with connect_sqlite(path) as conn:
        row = conn.execute(
            """
            SELECT current_node, latest_trace_id
            FROM research_graph_branches WHERE branch_id='branch-1'
            """
        ).fetchone()
    assert tuple(row) == ("data_contract", "trace-race")


def test_large_profile_is_referenced_without_copying_it_into_trace(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "graphs.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    initialize(path)
    large = profile_document(
        product_scope=["A.DCE"],
        source_scope=["Local"],
        probe=False,
        expanded=False,
        entries=[{
            "product": "A.DCE",
            "source": f"Local-{index}",
            "status": "available",
            "detail": "x" * 120,
        } for index in range(80)],
        as_of=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        data_contract_service,
        "availability_for_scope",
        lambda **_kwargs: large,
    )

    advance_graph_branch(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        edge_id="data_contract__factor_semantics",
        evidence=transition_evidence(),
    )

    with connect_sqlite(path) as conn:
        row = conn.execute(
            """
            SELECT b.current_node, b.latest_trace_id, t.evidence_json
            FROM research_graph_branches AS b
            JOIN research_graph_trace AS t
              ON t.trace_id=b.latest_trace_id
            WHERE b.branch_id='branch-1'
            """
        ).fetchone()
    assert row["current_node"] == "factor_semantics"
    assert row["latest_trace_id"] != "trace-bootstrap"
    assert len(row["evidence_json"].encode()) <= 6000
    assert '"detail"' not in row["evidence_json"]
