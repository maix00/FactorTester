"""One-time reconstruction of a branch obligation ledger from server history."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any

from .ledger import append_event, canonicalize_ledger, initialize_ledger
from .definitions import validate_definition_candidate
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
    current_by_id = {
        str(item["obligation_id"]): item for item in current
    }
    historical_changes = _historical_changes(contexts)
    replay = _history_baseline(
        current=current,
        historical_changes=historical_changes,
    )
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
    known_requirements: dict[str, dict[str, str]] = {
        str(item["requirement_id"]): deepcopy(item)
        for item in packet_requirements(packet)
    }
    for context in contexts:
        changes = context.get("obligation_changes") or []
        if context.get("side") != "target" or not changes:
            continue
        presentations = {
            str(item["obligation_ref"]): str(item["question_summary"])
            for item in context.get("obligation_presentations") or []
            if isinstance(item, dict) and item.get("obligation_ref")
        }
        titles = {
            str(item["obligation_ref"]): str(item.get("title_zh") or "")
            for item in context.get("obligation_presentations") or []
            if isinstance(item, dict) and item.get("obligation_ref")
        }
        deltas = [
            _migration_delta(
                item,
                replay,
                presentations,
                titles,
                source_ref=str(context["step_ref"]),
                current_by_id=current_by_id,
                historical_changes=historical_changes,
            )
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
                "obligation_delta": deepcopy(deltas),
                "server_obligation_delta": deepcopy(changes),
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
    titles: dict[str, str],
    *,
    source_ref: str,
    current_by_id: dict[str, dict[str, Any]],
    historical_changes: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    delta = deepcopy(value)
    obligation_id = str(delta["obligation_id"])
    existing = next((
        item for item in replay
        if str(item.get("obligation_id") or "") == obligation_id
    ), None)
    before = list(delta.get("from_requirement_refs") or [])
    after = _creation_refs(
        obligation_id=obligation_id,
        delta=delta,
        current_by_id=current_by_id,
        historical_changes=historical_changes,
    )
    question = presentations.get(f"obligation:{obligation_id}", "")
    title = titles.get(f"obligation:{obligation_id}", "")
    presentation_definition = {
        "title_zh": title,
        "epistemic_question": question,
    }
    if existing is not None:
        validate_definition_candidate(
            existing,
            presentation_definition,
            obligation_id=obligation_id,
            source=f"historical transition {source_ref}",
            ignore_blank_candidate=True,
        )
    if existing is None and delta["from_state"] != "absent":
        seeded = deepcopy(current_by_id.get(obligation_id) or {})
        seeded.update({
            "obligation_id": obligation_id,
            "status": str(delta["from_state"]),
            "epistemic_question": (
                question or str(seeded.get("epistemic_question") or "")
            ),
            "title_zh": title or str(seeded.get("title_zh") or ""),
            "requirement_refs": (
                before
                if "from_requirement_refs" in delta
                else list(seeded.get("requirement_refs") or [])
            ),
        })
        seeded.setdefault("materiality", "")
        seeded.setdefault("detail_ref", "")
        replay.append(seeded)
    if delta["from_state"] == "absent":
        body = deepcopy(current_by_id.get(obligation_id) or {})
        body.update({
            "obligation_id": obligation_id,
            "status": str(delta["to_state"]),
            "epistemic_question": (
                question or str(body.get("epistemic_question") or "")
            ),
            "title_zh": title or str(body.get("title_zh") or ""),
            "requirement_refs": after,
        })
        body.setdefault("materiality", "")
        body.setdefault("detail_ref", "")
        delta["obligation"] = body
        delta["from_requirement_refs"] = []
        delta["to_requirement_refs"] = after
    return delta


def _historical_changes(
    contexts: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for context in contexts:
        if context.get("side") != "target":
            continue
        for item in context.get("obligation_changes") or []:
            if not isinstance(item, dict) or not item.get("obligation_id"):
                continue
            result.setdefault(str(item["obligation_id"]), []).append(item)
    return result


def _history_baseline(
    *,
    current: list[dict[str, Any]],
    historical_changes: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Keep obligations that predate the available branch timeline."""
    return [
        deepcopy(item)
        for item in current
        if str(item["obligation_id"]) not in historical_changes
    ]


def _creation_refs(
    *,
    obligation_id: str,
    delta: dict[str, Any],
    current_by_id: dict[str, dict[str, Any]],
    historical_changes: dict[str, list[dict[str, Any]]],
) -> list[str]:
    explicit = delta.get("to_requirement_refs")
    if isinstance(explicit, list):
        return list(explicit)
    changes = historical_changes.get(obligation_id) or []
    try:
        index = next(
            offset for offset, item in enumerate(changes)
            if item is delta or item == delta
        )
    except StopIteration:
        index = -1
    for later in changes[index + 1:]:
        before = later.get("from_requirement_refs")
        if isinstance(before, list):
            return list(before)
    current = current_by_id.get(obligation_id) or {}
    return list(current.get("requirement_refs") or [])


def _validate_current_projection(
    replay: list[dict[str, Any]],
    current: list[dict[str, Any]],
) -> None:
    current_by_id = {
        str(item["obligation_id"]): item for item in current
    }
    replay_by_id = {
        str(item["obligation_id"]): item for item in replay
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
            continue
        validate_definition_candidate(
            item,
            accepted,
            obligation_id=obligation_id,
            source="current server projection",
            ignore_blank_candidate=True,
        )
    for obligation_id in current_by_id:
        if obligation_id not in replay_by_id:
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
