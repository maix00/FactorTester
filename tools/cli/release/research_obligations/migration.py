"""One-time reconstruction of a branch obligation ledger from server history."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any

from .ledger import append_event, canonicalize_ledger, initialize_ledger
from .packet import (
    checkpoint_ref,
    obligations as packet_obligations,
    requirements as packet_requirements,
)
from .projection import apply_obligation_deltas, project_requirement_coverage


def ledger_from_history(
    *,
    branch_ref: str,
    packet: dict[str, Any],
    contexts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a current projection with immutable accepted historical deltas."""
    current = packet_obligations(packet)
    ledger = initialize_ledger(
        branch_ref=branch_ref,
        graph_ref=str(packet.get("graph") or ""),
        current_node=str((packet.get("node") or {}).get("node_id") or ""),
        context_ref=str(packet.get("context_ref") or ""),
        checkpoint_ref=checkpoint_ref(packet),
        obligations=current,
    )
    ledger["current_projection"]["requirement_coverage"] = (
        project_requirement_coverage(
            requirements=packet_requirements(packet),
            obligations=current,
        )
    )
    ledger = canonicalize_ledger(ledger)
    replay: list[dict[str, Any]] = []
    known_requirements: dict[str, dict[str, str]] = {}
    for context in contexts:
        changes = context.get("obligation_changes") or []
        if context.get("side") != "target" or not changes:
            continue
        presentations = {
            str(item["obligation_ref"]): str(item["question_summary"])
            for item in context.get("obligation_presentations") or []
            if isinstance(item, dict) and item.get("obligation_ref")
        }
        deltas = [
            _migration_delta(item, replay, presentations)
            for item in changes
        ]
        replay, changed = apply_obligation_deltas(replay, deltas)
        for item in deltas:
            for requirement_id in [
                *(item.get("from_requirement_refs") or []),
                *(item.get("to_requirement_refs") or []),
            ]:
                known_requirements.setdefault(str(requirement_id), {
                    "requirement_id": str(requirement_id),
                    "title_zh": "",
                })
        coverage = project_requirement_coverage(
            requirements=list(known_requirements.values()),
            obligations=replay,
            changed_obligation_refs=changed,
        )
        step_ref = str(context["step_ref"])
        token = hashlib.sha256(step_ref.encode()).hexdigest()[:48]
        ledger = append_event(
            ledger,
            event_type="obligation_change",
            event_id=hashlib.sha256(
                f"history:{step_ref}".encode()
            ).hexdigest()[:32],
            created_at=float(context["created_at"]),
            payload={
                "agent_id": "server-history-migration",
                "node_id": str(context.get("to_node") or ""),
                "report_submission_sequence": 0,
                "obligation_delta": deepcopy(changes),
                "obligation_presentations": presentations,
                "obligations_snapshot": deepcopy(replay),
                "coverage_snapshot": coverage,
                "migration_source": step_ref,
                "report_components": {
                    "special_id": f"obligation-changes-{token}",
                    "change_table_id": f"obligation-change-table-{token}",
                    "current_table_id": (
                        f"current-obligation-table-{token}"
                    ),
                    "requirement_table_id": (
                        f"obligation-requirement-table-{token}"
                    ),
                },
            },
        )
    _validate_current_projection(replay, current)
    return canonicalize_ledger(ledger)


def _migration_delta(
    value: dict[str, Any],
    replay: list[dict[str, Any]],
    presentations: dict[str, str],
) -> dict[str, Any]:
    delta = deepcopy(value)
    obligation_id = str(delta["obligation_id"])
    existing = next((
        item for item in replay
        if str(item.get("obligation_id") or "") == obligation_id
    ), None)
    before = list(delta.get("from_requirement_refs") or [])
    after = list(delta.get("to_requirement_refs") or [])
    question = presentations.get(f"obligation:{obligation_id}", "")
    if existing is None and delta["from_state"] != "absent":
        replay.append({
            "obligation_id": obligation_id,
            "status": str(delta["from_state"]),
            "materiality": "",
            "epistemic_question": question,
            "requirement_refs": before,
            "detail_ref": "",
        })
    if delta["from_state"] == "absent":
        delta["obligation"] = {
            "obligation_id": obligation_id,
            "status": str(delta["to_state"]),
            "materiality": "",
            "epistemic_question": question,
            "requirement_refs": after,
            "detail_ref": "",
        }
    return delta


def _validate_current_projection(
    replay: list[dict[str, Any]],
    current: list[dict[str, Any]],
) -> None:
    current_by_id = {
        str(item["obligation_id"]): item for item in current
    }
    mismatches = []
    for item in replay:
        obligation_id = str(item["obligation_id"])
        accepted = current_by_id.get(obligation_id)
        if accepted is None:
            if item.get("status") != "rejected":
                mismatches.append(obligation_id)
            continue
        if (
            str(item.get("status") or "")
            != str(accepted.get("status") or "")
            or _refs(item) != _refs(accepted)
        ):
            mismatches.append(obligation_id)
    if mismatches:
        raise ValueError(
            "server obligation history does not reproduce current projection: "
            + ", ".join(sorted(mismatches))
        )


def _refs(value: dict[str, Any]) -> list[str]:
    return sorted(
        str(item).removeprefix("requirement:")
        for item in value.get("requirement_refs") or []
    )
