"""Replay immutable traces into capability-detour placement state."""

from __future__ import annotations

from copy import deepcopy
import sqlite3
from typing import Any, Iterable

from .replay_delta import (
    continuation_state,
    evidence_payload,
    persisted_delta,
    project_persisted_delta,
)
from .replay_legacy import (
    historical_container,
    legacy_delta,
    legacy_exit,
)
from .routing import project_transition
from .state import RESUME_EDGE_PREFIX


def reconstruct_from_trace(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    branch_id: str,
) -> dict[str, Any] | None:
    rows = conn.execute(
        """
        SELECT trace_id, edge_id, from_node, to_node, evidence_json
        FROM research_graph_trace
        WHERE instance_id=? AND branch_id=?
        ORDER BY created_at, rowid
        """,
        (instance_id, branch_id),
    ).fetchall()
    return project_trace_rows(rows)["state"]


def project_trace_rows(rows: Iterable[Any]) -> dict[str, Any]:
    """Return declarative before/after placement for every ordered trace."""
    state = None
    items = {}
    for row in rows:
        trace_id = str(row["trace_id"] or "")
        edge_id = str(row["edge_id"] or "")
        source = str(row["from_node"] or "")
        target = str(row["to_node"] or "")
        evidence = evidence_payload(row["evidence_json"])
        inherited = (
            continuation_state(evidence)
            if edge_id == "__graph_continuation__" else None
        )
        before = inherited if inherited is not None else state
        persisted = persisted_delta(evidence)
        legacy_untracked = persisted is None and not edge_id.startswith(
            RESUME_EDGE_PREFIX
        )
        if edge_id == "__graph_continuation__":
            after, delta = before, None
        elif persisted is not None:
            before, after, delta = project_persisted_delta(
                before,
                persisted,
                trace_id=trace_id,
            )
            legacy_untracked = False
        elif legacy_exit(before, edge_id, source, target):
            after = None
            delta = legacy_delta(
                before,
                trace_id,
                exit_node=target,
            )
        else:
            projection = project_transition(
                before,
                edge_id=edge_id,
                source_node=source,
                target_node=target,
                trace_id=trace_id,
            )
            after, delta = projection["state"], projection["delta"]
        source_container = historical_container(
            node_id=source,
            state=before,
            legacy_untracked=legacy_untracked,
        )
        transition_container = (
            deepcopy(delta["report_container"])
            if delta else historical_container(
                node_id=target,
                state=after,
                legacy_untracked=legacy_untracked,
            )
        )
        items[trace_id] = {
            "source_report_container": source_container,
            "report_container": transition_container,
            "capability_detour": {
                "state_before": deepcopy(before),
                "delta": deepcopy(delta),
                "state_after": deepcopy(after),
            },
        }
        state = after
    return {"state": state, "items": items}
