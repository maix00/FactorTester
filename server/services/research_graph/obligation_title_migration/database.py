"""Transactional migration of persisted Research Cycle title history."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import orjson

from server.services.research_graph.branch.trace_compaction import (
    RESEARCH_CYCLE_EVENTS_OBJECT_KIND,
    compact_research_cycle_event_receipts,
)
from server.services.research_graph.graph_objects import (
    insert_graph_objects,
    load_graph_objects,
    prepare_graph_object,
)
from server.services.research_graph.protocol import (
    serialize_bounded_trace_evidence,
)
from tools.data.sqlite.db import connect_sqlite

from .content import (
    migrate_checkpoint,
    migrate_checkpoint_with_hashes,
    migrate_events,
)


def migrate_obligation_titles(
    *,
    db_path: str | Path,
    titles: dict[str, str],
) -> dict[str, int]:
    """Rewrite all dependent hashes atomically from a reviewed title map."""
    _validate_titles(titles)
    with connect_sqlite(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            report = _migrate_rows(conn, titles)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return report


def _migrate_rows(conn, titles: dict[str, str]) -> dict[str, int]:
    rows = list(conn.execute(
        """
        SELECT trace_id, instance_id, evidence_json, created_at
        FROM research_graph_trace
        ORDER BY created_at, trace_id
        """
    ))
    pending = {str(row["trace_id"]): row for row in rows}
    processed: set[str] = set()
    checkpoints: dict[str, dict[str, Any]] = {}
    proposal_hashes: dict[str, dict[str, str]] = {}
    updates: list[tuple[str, str]] = []
    new_objects: list[dict[str, Any]] = []
    compacted = 0
    while pending:
        progressed = False
        for trace_id, row in list(pending.items()):
            evidence = _object(row["evidence_json"], "trace evidence")
            checkpoint = evidence.get("research_cycle_checkpoint")
            cycle = evidence.get("research_cycle")
            if not isinstance(checkpoint, dict) or not isinstance(cycle, dict):
                pending.pop(trace_id)
                processed.add(trace_id)
                progressed = True
                continue
            parent_id = str(
                cycle.get("parent_trace_ref") or ""
            ).removeprefix("trace:")
            if parent_id and parent_id not in processed:
                continue
            previous = checkpoints.get(parent_id)
            try:
                migrated, prepared, trace_hashes = _migrate_trace(
                    conn=conn,
                    instance_id=str(row["instance_id"]),
                    evidence=evidence,
                    previous_checkpoint=previous,
                    previous_proposal_hashes=proposal_hashes.get(parent_id),
                    titles=titles,
                )
            except Exception as exc:
                raise ValueError(
                    f"obligation title migration failed at trace {trace_id}: "
                    f"{exc}"
                ) from exc
            checkpoints[trace_id] = migrated["research_cycle_checkpoint"]
            proposal_hashes[trace_id] = trace_hashes
            encoded = serialize_bounded_trace_evidence(migrated)
            if encoded != str(row["evidence_json"]):
                updates.append((encoded, trace_id))
            if prepared is not None:
                new_objects.append(prepared)
                compacted += 1
            pending.pop(trace_id)
            processed.add(trace_id)
            progressed = True
        if not progressed:
            raise ValueError(
                "research cycle trace parents cannot be resolved: "
                + ", ".join(sorted(pending))
            )
    insert_graph_objects(conn, new_objects)
    conn.executemany(
        "UPDATE research_graph_trace SET evidence_json=? WHERE trace_id=?",
        updates,
    )
    return {
        "trace_rows_scanned": len(rows),
        "trace_rows_updated": len(updates),
        "event_bundles_written": compacted,
        "reviewed_title_count": len(titles),
    }


def _migrate_trace(
    *,
    conn,
    instance_id: str,
    evidence: dict[str, Any],
    previous_checkpoint: dict[str, Any] | None,
    previous_proposal_hashes: dict[str, str] | None,
    titles: dict[str, str],
) -> tuple[
    dict[str, Any],
    dict[str, Any] | None,
    dict[str, str],
]:
    value = deepcopy(evidence)
    cycle = deepcopy(value["research_cycle"])
    stored, stored_hashes = migrate_checkpoint_with_hashes(
        value["research_cycle_checkpoint"], titles=titles,
    )
    events, object_row = _events(conn, cycle, instance_id)
    if previous_checkpoint is None:
        initial = cycle.get("initial_checkpoint")
        base, base_hashes = migrate_checkpoint_with_hashes(
            initial if isinstance(initial, dict) else stored,
            titles=titles,
        )
    else:
        base = previous_checkpoint
        base_hashes = dict(previous_proposal_hashes or {})
    migrated_events, projected = migrate_events(
        base,
        events,
        titles=titles,
        proposal_hashes=base_hashes,
    )
    if projected["projection_hash"] != stored["projection_hash"]:
        raise ValueError(
            "title migration changed non-title Research Cycle semantics"
        )
    cycle["checkpoint_before_hash"] = base["projection_hash"]
    if isinstance(cycle.get("initial_checkpoint"), dict):
        cycle["initial_checkpoint"] = base
    prepared = None
    if object_row is None:
        cycle["events"] = migrated_events
    else:
        old_ref = str(cycle.get("events_ref") or "")
        prepared = prepare_graph_object(
            str(object_row["owner"]),
            instance_id,
            RESEARCH_CYCLE_EVENTS_OBJECT_KIND,
            {"schema_version": 1, "events": migrated_events},
        )
        cycle["events_ref"] = prepared["object_ref"]
        cycle["event_receipts"] = compact_research_cycle_event_receipts(
            migrated_events
        )
        if prepared["object_ref"] == old_ref:
            prepared = None
    value["research_cycle"] = cycle
    value["research_cycle_checkpoint"] = projected
    return value, prepared, stored_hashes


def _events(conn, cycle: dict[str, Any], instance_id: str):
    events = cycle.get("events")
    if isinstance(events, list):
        return _restore_proposal_hashes(
            events, cycle.get("event_receipts"),
        ), None
    ref = str(cycle.get("events_ref") or "")
    if not ref:
        raise ValueError("research cycle trace has no event source")
    object_hash = ref.removeprefix("research-graph-object:sha256:")
    row = conn.execute(
        """
        SELECT owner, instance_id
        FROM research_graph_objects
        WHERE object_hash=? AND object_kind=?
        """,
        (object_hash, RESEARCH_CYCLE_EVENTS_OBJECT_KIND),
    ).fetchone()
    if row is None or str(row["instance_id"]) != instance_id:
        raise ValueError("research cycle event bundle identity is invalid")
    body = load_graph_objects(
        conn,
        str(row["owner"]),
        instance_id,
        [ref],
        {ref: RESEARCH_CYCLE_EVENTS_OBJECT_KIND},
    )[ref]
    events = body.get("events")
    if not isinstance(events, list):
        raise ValueError("research cycle event bundle is invalid")
    return _restore_proposal_hashes(
        events, cycle.get("event_receipts"),
    ), row


def _restore_proposal_hashes(
    events: list[dict[str, Any]],
    receipts: Any,
) -> list[dict[str, Any]]:
    values = deepcopy(events)
    if not isinstance(receipts, list) or len(receipts) != len(values):
        return values
    for event, receipt in zip(values, receipts, strict=True):
        if (
            isinstance(event, dict)
            and isinstance(receipt, dict)
            and event.get("event_type") in {
                "adjudication_proposed", "closure_proposed",
            }
            and isinstance(event.get("proposal"), dict)
            and not event["proposal"].get("proposal_hash")
            and receipt.get("proposal_hash")
        ):
            event["proposal"]["proposal_hash"] = receipt["proposal_hash"]
    return values


def _object(value: Any, field: str) -> dict[str, Any]:
    try:
        parsed = orjson.loads(value)
    except (TypeError, orjson.JSONDecodeError) as exc:
        raise ValueError(f"{field} is invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{field} must be an object")
    return parsed


def _validate_titles(titles: dict[str, str]) -> None:
    if not isinstance(titles, dict) or not titles:
        raise ValueError("reviewed obligation titles must be a non-empty object")
    for obligation_id, title in titles.items():
        if (
            not isinstance(obligation_id, str)
            or not obligation_id
            or not isinstance(title, str)
            or not title.strip()
            or "\n" in title
            or len(title.strip()) > 32
        ):
            raise ValueError(
                "reviewed obligation titles must be one line and at most "
                "32 characters"
            )
