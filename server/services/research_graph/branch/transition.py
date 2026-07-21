"""Atomic Graph branch transitions and bounded trace persistence."""

from __future__ import annotations

from copy import deepcopy
import time
import uuid
from typing import Any

import orjson

import settings as Settings
from server.services.research_graph.branch import server_actions
from server.services.research_graph.branch.projection import (
    normalize_capability_resolution,
    serialize_capability_resolution,
    validate_trial_plan_hash,
)
from server.services.research_graph.branch.repository import (
    branch_payload,
    load_current_branch_resolution,
    load_instance_branch_with_latest_trace,
)
from server.services.research_graph.branch.guards import (
    system_transition_guard_facts,
)
from server.services.research_graph.branch.research_cycle import (
    checkpoint_from_branch_row,
    prepare_research_cycle_trace,
    release_trial_plan_for_new_hypothesis,
)
from server.services.research_graph.capability_resolution import (
    missing_required_capabilities,
    validate_resolution_against_node,
)
from server.services.research_graph.research_cycle.evidence import (
    validate_agent_evidence_payload,
)
from server.services.research_graph.research_cycle.routing import (
    accepted_adjudication_action,
    adjudication_route_guards,
)
from server.services.research_graph.research_cycle.authority import (
    validate_live_event_authorities,
)
from server.services.research_graph.protocol import (
    assert_no_skill_identity,
    loads,
    merge_bounded_evidence_refs,
    serialize_bounded_trace_evidence,
)
from server.services.research_graph.report_checkpoint import (
    report_checkpoint_projection,
)
from server.services.research_graph.trial_plan.transition import (
    prepare_trial_plan_evidence,
    validate_trial_plan_cycle_binding,
    validate_trial_plan_transition,
)
from server.services.research_graph.trial_plan.stage_projection import (
    advance_trial_stage,
    project_trial_plan_stage,
    trial_stage_guard_facts,
)
from server.services.research_graph.versions import load_graph_from_conn
from tools.data.sqlite.db import connect_sqlite


def advance_graph_branch(
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
    edge_id: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(evidence, dict):
        raise ValueError("transition evidence must be an object")
    if "server_evidence" in evidence or "report_lineage" in evidence:
        raise ValueError("server evidence and report lineage are server-owned")
    evidence = validate_agent_evidence_payload(evidence)
    prepared_evidence, proposed_trial_plan_hash, has_trial_plan_body = (
        prepare_trial_plan_evidence(evidence)
    )
    persisted_evidence = deepcopy(prepared_evidence)
    persisted_evidence.pop("target_capability_resolution", None)
    persisted_evidence.pop("token_telemetry", None)
    assert_no_skill_identity(
        persisted_evidence,
        location="transition evidence",
    )
    # Reject obviously oversized payloads before opening a transaction. A
    # second check below includes the server-created receipt reference.
    serialize_bounded_trace_evidence(persisted_evidence)
    invocation_ids = prepared_evidence.get("agent_invocation_ids") or []
    if not isinstance(invocation_ids, list) or not all(
        isinstance(item, str) and item for item in invocation_ids
    ):
        raise ValueError("agent_invocation_ids must be an array")
    prepared_server_actions = server_actions.prepare(
        instance_id=instance_id,
        branch_id=branch_id,
        owner=owner,
        edge_id=edge_id,
        evidence=prepared_evidence,
    )
    prepared_evidence = server_actions.bind(
        prepared_evidence,
        prepared_server_actions,
    )
    persisted_evidence = server_actions.bind(
        persisted_evidence,
        prepared_server_actions,
    )
    serialize_bounded_trace_evidence(persisted_evidence)
    proposed_trial_plan_hash = validate_trial_plan_hash(
        proposed_trial_plan_hash
    )
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute("BEGIN IMMEDIATE")
        branch_row = load_instance_branch_with_latest_trace(
            conn,
            instance_id=instance_id,
            branch_id=branch_id,
            owner=owner,
        )
        if branch_row is None:
            raise KeyError("graph branch not found")
        branch = branch_payload(branch_row) or {}
        current_stage_projection = (
            loads(branch_row["trial_stage_projection_json"]) or {}
        )
        previous_cycle_checkpoint = checkpoint_from_branch_row(branch_row)
        cycle_update = prepared_evidence.get("research_cycle")
        if isinstance(cycle_update, dict):
            validate_live_event_authorities(
                owner_user_id=owner,
                events=cycle_update.get("events") or [],
                pending_adjudications=(
                    previous_cycle_checkpoint["pending_adjudications"]
                    if previous_cycle_checkpoint is not None else []
                ),
                pending_closure=(
                    previous_cycle_checkpoint["pending_closure"]
                    if previous_cycle_checkpoint is not None else None
                ),
                transition_invocation_ids=invocation_ids,
            )
        graph = load_graph_from_conn(
            conn,
            graph_id=str(branch_row["graph_id"]),
            version=int(branch_row["graph_version"]),
        ) or {}
        edge = next(
            (
                item
                for item in graph.get("edges") or []
                if str(item.get("edge_id") or "") == edge_id
            ),
            None,
        )
        if edge is None:
            raise KeyError("graph edge not found")
        server_actions.validate(
            row=branch_row,
            edge=edge,
            prepared=prepared_server_actions,
        )
        edge_from = str(edge.get("from_node") or "")
        if edge_from not in {branch["current_node"], "*"}:
            raise ValueError(
                f"edge {edge_id} does not leave current node "
                f"{branch['current_node']}"
            )
        if branch["status"] == "paused" and edge.get("edge_type") != "recovery":
            raise ValueError("paused branch only accepts a recovery edge")
        cycle_event, cycle_checkpoint = prepare_research_cycle_trace(
            update=cycle_update,
            previous_checkpoint=previous_cycle_checkpoint,
            latest_trace_id=str(branch_row["latest_trace_id"]),
        )
        route_action = accepted_adjudication_action(
            previous_checkpoint=previous_cycle_checkpoint,
            events=(
                cycle_update.get("events") or []
                if isinstance(cycle_update, dict)
                else []
            ),
        )
        cycle_events = (
            cycle_update.get("events") or []
            if isinstance(cycle_update, dict)
            else []
        )
        prepared_server_guard_facts = server_actions.guard_facts(
            prepared_server_actions
        )
        guard_evidence = {
            **prepared_evidence,
            **adjudication_route_guards(route_action),
            **trial_stage_guard_facts(
                projection=current_stage_projection,
                adjudication_action=route_action,
            ),
            "research_cycle_delta_applied": bool(cycle_events),
            **system_transition_guard_facts(
                branch_row=branch_row,
                cycle_checkpoint=cycle_checkpoint,
                provenance_integrity_status=str(
                    prepared_server_guard_facts.get(
                        "data_provenance_integrity_status"
                    ) or ""
                ),
            ),
            **prepared_server_guard_facts,
        }
        failed_guards = [
            key
            for key, expected in (edge.get("guard") or {}).items()
            if guard_evidence.get(key) != expected
        ]
        if failed_guards:
            raise ValueError(
                "transition guards not satisfied: " + ", ".join(failed_guards)
            )
        required_evidence = edge.get("required_evidence") or []
        evidence_refs = prepared_evidence.get("evidence_refs") or []
        if required_evidence and (
            not isinstance(evidence_refs, list) or not evidence_refs
        ):
            raise ValueError("transition requires evidence_refs")
        target_id = str(edge.get("to_node") or "")
        target = next(
            (
                item
                for item in graph.get("nodes") or []
                if str(item.get("node_id") or "") == target_id
            ),
            None,
        )
        if target is None:
            raise ValueError("transition target node is missing")
        supplied_resolution = prepared_evidence.get(
            "target_capability_resolution"
        )
        if supplied_resolution is not None:
            target_resolution = normalize_capability_resolution(
                supplied_resolution,
                node_id=target_id,
            )
            validate_resolution_against_node(
                graph=graph,
                node=target,
                resolution=target_resolution,
            )
        elif target_id == branch["current_node"]:
            target_resolution = load_current_branch_resolution(branch_row)
        else:
            target_resolution = normalize_capability_resolution(
                {"node_id": target_id},
                node_id=target_id,
            )
        missing_capabilities = missing_required_capabilities(
            target,
            target_resolution or {},
        )
        if missing_capabilities and target.get("kind") != "capability_gap":
            raise ValueError(
                "target node has unresolved capabilities: "
                + ", ".join(missing_capabilities)
                + "; use the declared capability-gap edge"
            )
        status = (
            "paused"
            if target.get("kind") == "capability_gap"
            or target_id == "code_improvement_required"
            else "running"
        )
        _, resolution_json, resolution_hash = (
            serialize_capability_resolution(
                target_resolution,
                node_id=target_id,
            )
        )
        starts_new_hypothesis = (
            edge.get("server_action")
            == "start_new_hypothesis_lineage"
        )
        if starts_new_hypothesis:
            if has_trial_plan_body or proposed_trial_plan_hash:
                raise ValueError(
                    "new hypothesis must release the old TrialPlan before "
                    "freezing another plan"
                )
        projected_trial_plan_hash = validate_trial_plan_transition(
            current_hash=str(branch_row["current_trial_plan_hash"]),
            proposed_hash=proposed_trial_plan_hash,
            has_body=has_trial_plan_body,
        )
        if starts_new_hypothesis:
            cycle_event, cycle_checkpoint = (
                release_trial_plan_for_new_hypothesis(
                    trace_event=cycle_event,
                    checkpoint=cycle_checkpoint,
                    current_trial_plan_hash=str(
                        branch_row["current_trial_plan_hash"]
                    ),
                )
            )
            projected_trial_plan_hash = ""
        if (
            cycle_checkpoint is not None
            and cycle_checkpoint["trial_plan_hash"]
            != projected_trial_plan_hash
        ):
            raise ValueError(
                "research_cycle TrialPlan hash does not match branch"
            )
        if has_trial_plan_body:
            validate_trial_plan_cycle_binding(
                trial_plan=prepared_evidence["trial_plan"],
                cycle_checkpoint=cycle_checkpoint,
            )
        if has_trial_plan_body and route_action == "advance_trial_stage":
            raise ValueError(
                "advance the stage before freezing its child TrialPlan"
            )
        projected_stage = (
            {} if starts_new_hypothesis else current_stage_projection
        )
        if has_trial_plan_body:
            projected_stage = project_trial_plan_stage(
                trial_plan=prepared_evidence["trial_plan"],
                trial_plan_hash=projected_trial_plan_hash,
                current_trial_plan_hash=str(
                    branch_row["current_trial_plan_hash"]
                ),
                current_projection=current_stage_projection,
                execution_node=target_id,
            )
        if route_action == "advance_trial_stage":
            projected_stage = advance_trial_stage(
                current_stage_projection
            )
        trace_evidence = deepcopy(persisted_evidence)
        trace_evidence.pop("research_cycle", None)
        if cycle_event is not None and cycle_checkpoint is not None:
            trace_evidence["research_cycle"] = cycle_event
            trace_evidence["research_cycle_checkpoint"] = cycle_checkpoint
        if supplied_resolution is not None:
            trace_evidence["target_capability_resolution_ref"] = (
                f"branch-resolution:{instance_id}:{branch_id}"
            )
        previous_trace_id = str(branch_row["latest_trace_id"] or "")
        trace_evidence["report_lineage"] = {
            "status": "linked" if previous_trace_id else "root",
            "predecessor_checkpoint_ref": (
                f"trace:{previous_trace_id}" if previous_trace_id else ""
            ),
        }
        trace_evidence_json = serialize_bounded_trace_evidence(trace_evidence)
        bounded_evidence_refs, omitted_evidence_count = (
            merge_bounded_evidence_refs(
                loads(branch_row["evidence_refs_json"]) or [],
                int(branch_row["omitted_evidence_count"]),
                trace_evidence.get("evidence_refs"),
            )
        )
        trace_id = uuid.uuid4().hex
        now = time.time()
        conn.execute(
            """
            UPDATE research_graph_branches
            SET current_node=?, status=?,
                current_capability_resolution_json=?,
                current_capability_resolution_hash=?,
                current_trial_plan_hash=?,
                trial_stage_projection_json=?,
                evidence_refs_json=?, omitted_evidence_count=?,
                latest_trace_id=?, updated_at=?
            WHERE branch_id=? AND instance_id=?
            """,
            (
                target_id,
                status,
                resolution_json,
                resolution_hash,
                projected_trial_plan_hash,
                orjson.dumps(projected_stage).decode(),
                orjson.dumps(bounded_evidence_refs).decode(),
                omitted_evidence_count,
                trace_id,
                now,
                branch_id,
                instance_id,
            ),
        )
        conn.execute(
            """
            INSERT INTO research_graph_trace (
                trace_id, instance_id, branch_id, edge_id, from_node, to_node,
                evidence_json, telemetry_json, actor, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trace_id,
                instance_id,
                branch_id,
                edge_id,
                branch["current_node"],
                target_id,
                trace_evidence_json,
                "{}",
                owner,
                now,
            ),
        )
        report_checkpoint = report_checkpoint_projection(
            instance_id=instance_id,
            branch_id=branch_id,
            workspace_id=str(branch_row["workspace_id"]),
            graph_id=str(branch_row["graph_id"]),
            graph_version=int(branch_row["graph_version"]),
            title=str(branch["label"]),
            product_group=str(branch_row["product_group"]),
            current_node=target_id,
            status=status,
            trace_id=trace_id,
            edge_id=edge_id,
            from_node=str(branch["current_node"]),
            created_at=now,
            checkpoint=cycle_checkpoint,
            trace_evidence=trace_evidence,
            evidence_refs=bounded_evidence_refs,
            omitted_evidence_count=omitted_evidence_count,
        )
    return {
        "branch_id": branch_id,
        "instance_id": instance_id,
        "label": branch["label"],
        "current_node": target_id,
        "status": status,
        "created_at": branch["created_at"],
        "updated_at": now,
        "report_checkpoint": report_checkpoint,
    }
