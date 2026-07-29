from __future__ import annotations

import orjson
from copy import deepcopy

import settings as Settings
from server.services.research_graph.branch.entry_resolution.events import (
    entry_resolution_event_envelope,
)
from server.services.research_graph.branch.entry_resolution.guard import (
    resume_guard_hash,
)
from server.services.research_graph.branch.entry_resolution.stack_state import (
    canonical_entry_resolution_state,
)
from server.services.research_graph.branch.repository import (
    load_instance_branch_row,
)
from server.services.research_graph.shadow_trace import replay_shadow_trace
from tests.server.data_contract_fixtures import graph, initialize
from tools.data.sqlite.db import connect_sqlite


def _install_equal_time_chain(path):
    initialize(path)
    value = graph()
    value["edges"].append({
        "edge_id": "factor_semantics__data_contract",
        "from_node": "factor_semantics",
        "to_node": "data_contract",
        "guard": {},
        "required_evidence": [],
    })
    graph_ref = (
        f"{value['graph_id']}@v{value['version']}#{value['content_hash']}"
    )
    checkpoint_ref = "research-cycle-checkpoint:" + "b" * 64
    frame = {
        "schema_version": 2,
        "entry_attempt_id": "entry-attempt-equal-time",
        "graph_ref": graph_ref,
        "target_node": "factor_semantics",
        "origin_checkpoint_ref": checkpoint_ref,
        "blocking_obligation_refs": [],
        "entry_requirement_refs": ["factor.expression"],
        "unresolved_entry_requirement_refs": ["factor.expression"],
        "status": "resolving",
        "resume_guard_hash": resume_guard_hash(
            graph_ref=graph_ref,
            target_node="factor_semantics",
            origin_checkpoint_ref=checkpoint_ref,
            blocking_obligation_refs=[],
            entry_requirement_refs=["factor.expression"],
        ),
    }
    active = canonical_entry_resolution_state(frame)
    resolved = deepcopy(active)
    resolved["frames"][-1]["status"] = "resolved"
    resolved["frames"][-1]["unresolved_entry_requirement_refs"] = []
    first = entry_resolution_event_envelope(
        before_state={}, departure_state={}, after_state=active,
        trace_ref="trace:z-first",
    )
    second = entry_resolution_event_envelope(
        before_state=active, departure_state=resolved, after_state={},
        trace_ref="trace:a-second",
    )
    with connect_sqlite(path) as conn:
        conn.execute("DELETE FROM research_graph_trace")
        conn.execute(
            "UPDATE research_graph_versions SET graph_json=?",
            (orjson.dumps(value).decode(),),
        )
        conn.executemany(
            """
            INSERT INTO research_graph_trace (
                trace_id, instance_id, branch_id, edge_id, from_node, to_node,
                evidence_json, telemetry_json, actor, created_at
            ) VALUES (?, 'instance-1', 'branch-1', ?, ?, ?, ?, '{}',
                      'alice', 1)
            """,
            [
                (
                    "z-first", "data_contract__factor_semantics",
                    "data_contract", "factor_semantics",
                    orjson.dumps({"entry_resolution_event": first}).decode(),
                ),
                (
                    "a-second", "factor_semantics__data_contract",
                    "factor_semantics", "data_contract",
                    orjson.dumps({"entry_resolution_event": second}).decode(),
                ),
            ],
        )
        conn.execute(
            "UPDATE research_graph_branches "
            "SET current_node='data_contract', latest_trace_id='a-second', "
            "entry_resolution_frame_json='{}' WHERE branch_id='branch-1'"
        )
        runtime = load_instance_branch_row(
            conn,
            instance_id="instance-1",
            branch_id="branch-1",
            owner="alice",
        )
    return value, runtime


def test_shadow_replay_uses_rowid_for_equal_timestamp_traces(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "equal-time.sqlite"
    value, runtime = _install_equal_time_chain(path)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)

    replay = replay_shadow_trace(graph=value, runtime=runtime)

    assert replay["passed"] is True, replay
    assert replay["transition_count"] == 2


def test_shadow_rejects_tampered_middle_event_with_same_latest_id(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "tampered-middle.sqlite"
    value, _ = _install_equal_time_chain(path)
    with connect_sqlite(path) as conn:
        row = conn.execute(
            "SELECT evidence_json FROM research_graph_trace "
            "WHERE trace_id='z-first'"
        ).fetchone()
        evidence = orjson.loads(row["evidence_json"])
        evidence["entry_resolution_event"]["stack_hash_after"] = "0" * 64
        conn.execute(
            "UPDATE research_graph_trace SET evidence_json=? "
            "WHERE trace_id='z-first'",
            (orjson.dumps(evidence).decode(),),
        )
        runtime = load_instance_branch_row(
            conn,
            instance_id="instance-1",
            branch_id="branch-1",
            owner="alice",
        )
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)

    assert replay_shadow_trace(graph=value, runtime=runtime)["passed"] is False
