"""Bounded Graph-path and Research Cycle shadow replay."""

from __future__ import annotations

import sqlite3
from typing import Any

import orjson

import settings as Settings
from server.services.research_graph.branch.continuation_store import (
    JOB_EVIDENCE_MODE,
    JOB_EVIDENCE_TARGET_NODE,
    PRE_TRIAL_CHECKPOINT_MODE,
    PRE_TRIAL_TARGET_NODE,
    SAME_NODE_REENTRY_MODE,
)
from server.services.research_graph.branch.capability_detour import (
    load_or_reconstruct as load_capability_detour,
)
from server.services.research_graph.branch.legacy_cycle import (
    continuation_checkpoint,
)
from server.services.research_graph.branch.requirement_preflight import (
    assess_requirement_continuation,
)
from server.services.research_graph.branch.version_lineage import (
    continuation_lineage_projection,
    load_descendant_lineage,
)
from server.services.research_graph.branch.entry_resolution import (
    initial_entry_resolution_frame,
)
from server.services.research_graph.branch.entry_resolution.events import (
    entry_resolution_event_envelope,
    entry_resolution_stack_hash,
)
from server.services.research_graph.branch.entry_resolution.replay import (
    empty_entry_stack_identity,
    replay_entry_resolution_event,
)
from server.services.research_graph.branch.entry_resolution.stack_state import (
    canonical_entry_resolution_state,
)
from server.services.research_graph.branch.trace_compaction import (
    RESEARCH_CYCLE_EVENTS_OBJECT_KIND,
)
from server.services.research_graph.graph_objects import load_graph_objects
from server.services.research_graph.protocol import json_hash
from server.services.research_graph.research_cycle.evidence import (
    validate_agent_evidence_envelope,
)
from server.services.research_graph.research_cycle.trace_replay import (
    verify_research_cycle_trace,
)
from server.services.research_graph.research_cycle.replay import (
    validate_research_cycle_checkpoint,
)
from tools.data.sqlite.db import connect_sqlite


MAX_REPLAY_ROWS = 1000


def replay_shadow_trace(
    *,
    graph: dict[str, Any],
    runtime: sqlite3.Row,
) -> dict[str, Any]:
    """Replay one bounded branch without mutating execution history."""
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT trace_id, edge_id, from_node, to_node, evidence_json
            FROM research_graph_trace
            WHERE instance_id=? AND branch_id=?
            ORDER BY created_at, rowid
            LIMIT ?
            """,
            (
                str(runtime["instance_id"]),
                str(runtime["branch_id"]),
                MAX_REPLAY_ROWS + 1,
            ),
        ).fetchall()
        evidence_rows = [
            orjson.loads(row["evidence_json"])
            for row in rows
        ]
        event_refs = {
            reference: RESEARCH_CYCLE_EVENTS_OBJECT_KIND
            for evidence in evidence_rows
            for reference in [_cycle_events_ref(evidence)]
            if reference
        }
        try:
            graph_objects = load_graph_objects(
                conn,
                str(runtime["owner"]),
                str(runtime["instance_id"]),
                event_refs,
                expected_kinds=event_refs,
            )
        except (KeyError, ValueError, TypeError):
            return _summary(
                current=str(graph.get("entry_node") or ""),
                expected=str(runtime["current_node"]),
                path=[],
                evidence_count=0,
                status="invalid",
            )
    if len(rows) > MAX_REPLAY_ROWS:
        raise ValueError("shadow replay trace exceeds bounded comparison rows")
    edges = {
        str(edge["edge_id"]): edge for edge in graph.get("edges") or []
    }
    current = str(
        graph.get("entry_node")
        or ((graph.get("nodes") or [{}])[0].get("node_id") or "")
    )
    if not current:
        raise ValueError("shadow Graph entry node is invalid")
    evidence_count = 0
    path: list[str] = []
    cycle_checkpoint: dict[str, Any] | None = None
    previous_trace_id = ""
    entry_stack_hash, entry_stack_depth = empty_entry_stack_identity()
    for row, evidence in zip(rows, evidence_rows, strict=True):
        if not isinstance(evidence, dict):
            return _summary(
                current=current,
                expected=str(runtime["current_node"]),
                path=path,
                evidence_count=evidence_count,
                status="invalid",
            )
        bootstrap_edge = str(row["edge_id"])
        if bootstrap_edge in {
            "__branch_fork__",
            "__graph_continuation__",
        }:
            is_continuation = bootstrap_edge == "__graph_continuation__"
            fork_node = _bootstrap_node(
                evidence,
                graph,
                continuation=is_continuation,
            )
            if (
                (
                    is_continuation
                    and not _continuation_bootstrap_valid(
                        evidence=evidence,
                        graph=graph,
                        runtime=runtime,
                        bootstrap_node=fork_node,
                        trace_id=str(row["trace_id"]),
                    )
                )
                or
                path
                or previous_trace_id
                or str(row["from_node"]) != fork_node
                or str(row["to_node"]) != fork_node
            ):
                return _summary(
                    current=current,
                    expected=str(runtime["current_node"]),
                    path=path,
                    evidence_count=evidence_count,
                    status="invalid",
                )
            cycle_checkpoint = _cycle_from_evidence(
                evidence=evidence,
                previous_checkpoint=None,
                previous_trace_id="",
                graph_objects=graph_objects,
                requirement_catalog=graph.get("requirement_catalog"),
            )
            if (
                evidence.get("research_cycle") is not None
                and cycle_checkpoint is None
            ):
                return _summary(
                    current=fork_node,
                    expected=str(runtime["current_node"]),
                    path=path,
                    evidence_count=evidence_count,
                    status="invalid",
                )
            current = fork_node
            previous_trace_id = str(row["trace_id"])
            if is_continuation:
                descriptor = evidence["graph_continuation"]
                entry_stack_hash = str(
                    descriptor["entry_resolution_stack_hash"]
                )
                entry_stack_depth = int(
                    descriptor["entry_resolution_stack_depth"]
                )
            continue
        edge = edges.get(str(row["edge_id"]))
        if (
            edge is None
            or str(row["from_node"]) != current
            or str(edge["from_node"]) not in {current, "*"}
            or str(row["to_node"]) != str(edge["to_node"])
        ):
            return _summary(
                current=current,
                expected=str(runtime["current_node"]),
                path=path,
                evidence_count=evidence_count,
                status="invalid",
            )
        factual = evidence.get("evidence_envelope")
        if isinstance(factual, dict) and factual.get("schema_version") == 2:
            evidence_count += len(factual.get("source_refs") or [])
        if (
            evidence.get("research_cycle") is not None
            or evidence.get("research_cycle_checkpoint") is not None
        ):
            cycle_checkpoint = _cycle_from_evidence(
                evidence=evidence,
                previous_checkpoint=cycle_checkpoint,
                previous_trace_id=previous_trace_id,
                graph_objects=graph_objects,
                requirement_catalog=graph.get("requirement_catalog"),
            )
            if cycle_checkpoint is None:
                return _summary(
                    current=current,
                    expected=str(runtime["current_node"]),
                    path=path,
                    evidence_count=evidence_count,
                    status="invalid",
                )
        try:
            entry_stack_hash, entry_stack_depth = (
                replay_entry_resolution_event(
                    event=evidence.get("entry_resolution_event"),
                    trace_id=str(row["trace_id"]),
                    stack_hash=entry_stack_hash,
                    depth=entry_stack_depth,
                )
            )
        except ValueError:
            return _summary(
                current=current,
                expected=str(runtime["current_node"]),
                path=path,
                evidence_count=evidence_count,
                status="invalid",
            )
        path.append(str(row["edge_id"]))
        current = str(row["to_node"])
        previous_trace_id = str(row["trace_id"])
    latest_matches = (
        (not rows and not str(runtime["latest_trace_id"]))
        or (
            bool(rows)
            and str(rows[-1]["trace_id"]) == str(runtime["latest_trace_id"])
        )
    )
    try:
        runtime_entry_state = canonical_entry_resolution_state(
            orjson.loads(runtime["entry_resolution_frame_json"] or "{}")
        )
    except (KeyError, TypeError, ValueError, orjson.JSONDecodeError):
        runtime_entry_state = None
    entry_matches = (
        runtime_entry_state is not None
        and entry_resolution_stack_hash(runtime_entry_state)
        == entry_stack_hash
        and len(runtime_entry_state["frames"]) == entry_stack_depth
    )
    return _summary(
        current=current,
        expected=str(runtime["current_node"]),
        path=path,
        evidence_count=evidence_count,
        status=(
            "current" if cycle_checkpoint is not None else "uninitialized"
        ),
        passed=(
            bool(rows)
            and (
                int(graph.get("schema_version") or 1) < 2
                or cycle_checkpoint is not None
            )
            and current == str(runtime["current_node"])
            and latest_matches
            and entry_matches
        ),
    )


def _bootstrap_node(
    evidence: dict[str, Any],
    graph: dict[str, Any],
    *,
    continuation: bool,
) -> str:
    fork = evidence.get(
        "graph_continuation" if continuation else "branch_fork"
    )
    fork_node = (
        str(
            fork.get("target_node" if continuation else "checkpoint_node")
            or ""
        )
        if isinstance(fork, dict)
        else ""
    )
    declared_nodes = {
        str(item.get("node_id") or "")
        for item in graph.get("nodes") or []
    }
    return fork_node if fork_node in declared_nodes else ""


def _continuation_bootstrap_valid(
    *,
    evidence: dict[str, Any],
    graph: dict[str, Any],
    runtime: sqlite3.Row,
    bootstrap_node: str,
    trace_id: str,
) -> bool:
    continuation = evidence.get("graph_continuation")
    server_evidence = evidence.get("server_evidence")
    envelope = (
        server_evidence.get("job_attempt")
        if isinstance(server_evidence, dict)
        else None
    )
    if not isinstance(continuation, dict):
        return False
    descriptor = continuation
    mode = str(descriptor.get("continuation_mode") or "")
    checkpoint = evidence.get("research_cycle_checkpoint")
    if not isinstance(checkpoint, dict):
        return False
    if (
        str(descriptor.get("owner") or "") != str(runtime["owner"])
        or str(descriptor.get("graph_id") or "") != str(runtime["graph_id"])
        or int(descriptor.get("target_graph_version") or 0)
        != int(runtime["graph_version"])
        or str(descriptor.get("target_graph_hash") or "")
        != str(graph.get("content_hash") or "")
        or str(descriptor.get("target_node") or "")
        != bootstrap_node
        or str(descriptor.get("workspace_id") or "")
        != str(runtime["workspace_id"])
        or str(checkpoint.get("projection_hash") or "")
        != str(descriptor.get("source_checkpoint_hash") or "")
    ):
        return False
    if mode == JOB_EVIDENCE_MODE:
        if (
            bootstrap_node != JOB_EVIDENCE_TARGET_NODE
            or not isinstance(envelope, dict)
        ):
            return False
        try:
            validated_envelope = validate_agent_evidence_envelope(envelope)
        except ValueError:
            return False
        facts = validated_envelope.get("facts") or {}
        if (
            str(descriptor.get("job_id") or "")
            != str(facts.get("job_id") or "")
            or str(descriptor.get("job_evidence_hash") or "")
            != str(validated_envelope.get("envelope_hash") or "")
        ):
            return False
    elif mode == PRE_TRIAL_CHECKPOINT_MODE:
        if (
            bootstrap_node != PRE_TRIAL_TARGET_NODE
            or server_evidence is not None
            or "job_id" in descriptor
            or "job_evidence_hash" in descriptor
            or str(checkpoint.get("trial_plan_hash") or "")
        ):
            return False
    elif mode == SAME_NODE_REENTRY_MODE:
        if (
            int(graph.get("schema_version") or 1) < 2
            or server_evidence is not None
            or "job_id" in descriptor
            or "job_evidence_hash" in descriptor
        ):
            return False
    else:
        return False
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        source = conn.execute(
            """
            SELECT i.instance_id, i.owner, i.graph_id, i.graph_version,
                   i.workspace_id,
                   i.work_package_id, v.graph_json, b.latest_trace_id,
                   b.branch_id, b.current_node, b.status,
                   b.current_trial_plan_hash, b.trial_stage_projection_json,
                   b.entry_resolution_frame_json,
                   t.evidence_json AS latest_trace_evidence_json
            FROM research_graph_instances i
            JOIN research_graph_branches b
              ON b.instance_id=i.instance_id
            JOIN research_graph_versions v
              ON v.graph_id=i.graph_id AND v.version=i.graph_version
            JOIN research_graph_trace t ON t.trace_id=b.latest_trace_id
            WHERE i.owner=? AND i.instance_id=? AND b.branch_id=?
            """,
            (
                str(runtime["owner"]),
                str(descriptor.get("source_instance_id") or ""),
                str(descriptor.get("source_branch_id") or ""),
            ),
        ).fetchone()
        source_detour = load_capability_detour(
            conn,
            instance_id=str(descriptor.get("source_instance_id") or ""),
            branch_id=str(descriptor.get("source_branch_id") or ""),
        )
        try:
            source_graph = (
                orjson.loads(source["graph_json"])
                if source is not None else None
            )
            expected_lineage_projection = (
                continuation_lineage_projection(
                    load_descendant_lineage(
                        conn,
                        graph_id=str(runtime["graph_id"]),
                        source_version=int(source["graph_version"]),
                        target_version=int(runtime["graph_version"]),
                    )
                )
                if source is not None
                else None
            )
            source_checkpoint, expected_legacy_bootstrap = (
                continuation_checkpoint(
                    conn,
                    source=source,
                    source_graph=source_graph,
                    capability_detour=source_detour,
                )
                if source is not None and isinstance(source_graph, dict)
                else (None, None)
            )
        except (KeyError, TypeError, ValueError, orjson.JSONDecodeError):
            source_graph = None
            source_checkpoint = None
            expected_legacy_bootstrap = None
            expected_lineage_projection = None
    if source is None:
        return False
    if descriptor.get("capability_detour") != source_detour:
        return False
    if (
        source_graph is None
        or source_checkpoint is None
        or descriptor.get("legacy_cycle_bootstrap")
        != expected_legacy_bootstrap
    ):
        return False
    lineage_fields = {
        "lineage_versions",
        "lineage_graph_hashes",
        "lineage_path_hash",
        "cumulative_change_manifests",
        "cumulative_change_manifest_hash",
    }
    declared_lineage_fields = lineage_fields & set(descriptor)
    if declared_lineage_fields:
        if (
            declared_lineage_fields != lineage_fields
            or expected_lineage_projection is None
            or any(
                descriptor.get(field)
                != expected_lineage_projection.get(field)
                for field in lineage_fields
            )
        ):
            return False
    elif int(graph.get("parent_version") or 0) != int(
        source["graph_version"]
    ):
        # Historical descriptors predate cumulative lineage binding and were
        # only legal for one direct parent step.
        return False
    try:
        source_entry_state = canonical_entry_resolution_state(
            orjson.loads(source["entry_resolution_frame_json"] or "{}")
        )
        target_entry_state = initial_entry_resolution_frame(
            descriptor,
            inherited_frame=source_entry_state,
            checkpoint=source_checkpoint,
        )
    except (TypeError, ValueError, orjson.JSONDecodeError):
        return False
    expected_entry_event = entry_resolution_event_envelope(
        before_state=source_entry_state,
        departure_state=source_entry_state,
        after_state=target_entry_state,
        trace_ref=f"trace:{trace_id}",
    )
    if (
        str(descriptor.get("entry_resolution_state_hash") or "")
        != json_hash(target_entry_state)
        or str(descriptor.get("entry_resolution_stack_hash") or "")
        != entry_resolution_stack_hash(target_entry_state)
        or int(descriptor.get("entry_resolution_stack_depth") or 0)
        != len(target_entry_state["frames"])
        or evidence.get("entry_resolution_event") != expected_entry_event
    ):
        return False
    if mode == SAME_NODE_REENTRY_MODE:
        if (
            int(graph.get("schema_version") or 1) < 2
            or bootstrap_node != str(source["current_node"])
            or server_evidence is not None
            or "job_id" in descriptor
            or "job_evidence_hash" in descriptor
        ):
            return False
        expected_requirement_preflight = assess_requirement_continuation(
            source_graph=source_graph,
            target_graph=graph,
            target_node=str(source["current_node"]),
        )
        if (
            descriptor.get("requirement_preflight")
            != expected_requirement_preflight
        ):
            return False
    return (
        str(source["graph_id"]) == str(descriptor.get("graph_id") or "")
        and int(source["graph_version"])
        == int(descriptor.get("source_graph_version") or 0)
        and str(source["workspace_id"])
        == str(descriptor.get("workspace_id") or "")
        and str(source_graph.get("content_hash") or "")
        == str(descriptor.get("source_graph_hash") or "")
        and str(source["latest_trace_id"])
        == str(descriptor.get("source_trace_id") or "")
        and str(source_checkpoint.get("projection_hash") or "")
        == str(descriptor.get("source_checkpoint_hash") or "")
    )


def _cycle_from_evidence(
    *,
    evidence: dict[str, Any],
    previous_checkpoint: dict[str, Any] | None,
    previous_trace_id: str,
    graph_objects: dict[str, dict[str, Any]],
    requirement_catalog: dict[str, Any] | None,
) -> dict[str, Any] | None:
    continuation = evidence.get("graph_continuation")
    if previous_checkpoint is None and isinstance(continuation, dict):
        event = evidence.get("research_cycle")
        checkpoint = evidence.get("research_cycle_checkpoint")
        try:
            projected = validate_research_cycle_checkpoint(checkpoint)
        except ValueError:
            return None
        source_trace_ref = (
            f"trace:{continuation.get('source_trace_id') or ''}"
        )
        if (
            not isinstance(event, dict)
            or event.get("schema_version") != 1
            or event.get("parent_trace_ref") != source_trace_ref
            or event.get("checkpoint_before_hash")
                != projected["projection_hash"]
            or event.get("events") != []
            or "bootstrap_checkpoint" in event
            or continuation.get("source_checkpoint_hash")
                != projected["projection_hash"]
        ):
            return None
        return projected
    try:
        return verify_research_cycle_trace(
            previous_checkpoint=previous_checkpoint,
            previous_trace_id=previous_trace_id,
            event=evidence.get("research_cycle"),
            projected_checkpoint=evidence.get(
                "research_cycle_checkpoint"
            ),
            resolved_events=_resolved_cycle_events(
                evidence,
                graph_objects,
            ),
            requirement_catalog=requirement_catalog,
        )
    except ValueError:
        return None


def _cycle_events_ref(evidence: Any) -> str:
    cycle = evidence.get("research_cycle") if isinstance(evidence, dict) else None
    if not isinstance(cycle, dict):
        return ""
    reference = cycle.get("events_ref")
    return str(reference) if isinstance(reference, str) else ""


def _resolved_cycle_events(
    evidence: dict[str, Any],
    graph_objects: dict[str, dict[str, Any]],
) -> list[dict[str, Any]] | None:
    reference = _cycle_events_ref(evidence)
    if not reference:
        return None
    value = graph_objects.get(reference)
    events = value.get("events") if isinstance(value, dict) else None
    if not isinstance(events, list) or not all(
        isinstance(item, dict) for item in events
    ):
        raise ValueError("research cycle event bundle is invalid")
    return events


def _summary(
    *,
    current: str,
    expected: str,
    path: list[str],
    evidence_count: int,
    status: str,
    passed: bool = False,
) -> dict[str, Any]:
    return {
        "passed": passed,
        "transition_count": len(path),
        "path_hash": json_hash(path),
        "evidence_ref_count": evidence_count,
        "derived_node": current,
        "projected_node": expected,
        "research_cycle_status": status,
    }
