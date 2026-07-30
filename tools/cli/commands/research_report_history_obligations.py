"""Rebuild obligation-change report sections from persisted Graph history."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any

from tools.cli.release.research_obligations.projection import (
    apply_obligation_deltas,
    project_requirement_coverage,
)
from tools.cli.release.research_obligations.reporting import (
    obligation_change_operations as ledger_report_operations,
)
from tools.cli.release.research_reporting.node_titles import node_title_zh


def obligation_change_operations(
    contexts: list[dict[str, Any]],
    *,
    parent_by_step: dict[str, str],
    components: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Return an idempotent two-table migration for historical changes."""
    operations: list[dict[str, Any]] = []
    episodes = 0
    projection: list[dict[str, Any]] = []
    known_requirements: dict[str, dict[str, str]] = {}
    for context in contexts:
        changes = context.get("obligation_changes") or []
        if context.get("side") != "target" or not changes:
            continue
        step_ref = str(context["step_ref"])
        parent_id = parent_by_step.get(step_ref)
        if not parent_id:
            raise ValueError(
                "obligation changes have no reconciled report container"
            )
        episodes += 1
        presentations = {
            str(item["obligation_ref"]): str(item["question_summary"])
            for item in context.get("obligation_presentations") or []
        }
        obligation_titles = {
            str(item["obligation_ref"]): str(item.get("title_zh") or "")
            for item in context.get("obligation_presentations") or []
        }
        for item in context.get("requirement_presentations") or []:
            requirement_id = str(
                item.get("requirement_id") or ""
            ).removeprefix("requirement:")
            if requirement_id:
                known_requirements[requirement_id] = {
                    "requirement_id": requirement_id,
                    "title_zh": str(item.get("title_zh") or ""),
                }
        deltas = [
            _replay_delta(
                item, projection, presentations, obligation_titles,
            )
            for item in changes
        ]
        projection, changed = apply_obligation_deltas(projection, deltas)
        for delta in deltas:
            for requirement_id in [
                *(delta.get("from_requirement_refs") or []),
                *(delta.get("to_requirement_refs") or []),
            ]:
                identifier = str(requirement_id).removeprefix("requirement:")
                if not str(
                    (known_requirements.get(identifier) or {}).get("title_zh")
                    or ""
                ).strip():
                    raise ValueError(
                        "historical requirement has no title_zh: "
                        + identifier
                    )
        coverage = project_requirement_coverage(
            requirements=list(known_requirements.values()),
            obligations=projection,
            changed_obligation_refs=changed,
        )
        token = _digest(step_ref)
        event = {
            "event_id": f"history:{step_ref}",
            "sequence": episodes,
            "obligation_delta": changes,
            "obligation_presentations": presentations,
            "obligations_snapshot": deepcopy(projection),
            "coverage_snapshot": coverage,
        }
        desired, _ = ledger_report_operations(
            event=event, parent_id=parent_id,
        )
        desired[0].update({
            "component_id": f"obligation-changes-{token}",
            "title": (
                f"{node_title_zh(str(context['from_node']))} → "
                f"{node_title_zh(str(context['to_node']))}"
            ),
            "body": f"该研究图转换改变了 {len(changes)} 项研究义务",
            "content": {
                "step_ref": step_ref,
                "change_count": len(changes),
            },
        })
        existing_special = components.get(desired[0]["component_id"])
        if existing_special is not None:
            # Historical obligation sections can already carry stable
            # obligation bindings authored by the legacy migration.  The new
            # three-table projection must preserve those links instead of
            # repeatedly attempting to replace them with an empty list.
            desired[0]["bindings"] = deepcopy(
                existing_special.get("bindings") or []
            )
        desired[1]["component_id"] = f"obligation-change-table-{token}"
        desired[1]["parent_id"] = desired[0]["component_id"]
        desired[1]["bindings"] = _retarget_bindings(
            desired[1]["bindings"], desired[1]["component_id"],
        )
        desired[2]["component_id"] = f"current-obligation-table-{token}"
        desired[2]["parent_id"] = desired[0]["component_id"]
        desired[2]["bindings"] = _retarget_bindings(
            desired[2]["bindings"], desired[2]["component_id"],
        )
        desired[3]["component_id"] = (
            f"obligation-requirement-table-{token}"
        )
        desired[3]["parent_id"] = desired[0]["component_id"]
        desired[3]["bindings"] = _retarget_bindings(
            desired[3]["bindings"], desired[3]["component_id"],
        )
        for operation in desired:
            _append_idempotent(
                operations=operations,
                components=components,
                operation=operation,
            )
    return operations, episodes


def _replay_delta(
    value: dict[str, Any],
    projection: list[dict[str, Any]],
    presentations: dict[str, str],
    titles: dict[str, str],
) -> dict[str, Any]:
    delta = deepcopy(value)
    obligation_id = str(delta["obligation_id"])
    existing = next((
        item for item in projection
        if str(item.get("obligation_id") or "") == obligation_id
    ), None)
    before = list(delta.get("from_requirement_refs") or [])
    after = list(delta.get("to_requirement_refs") or [])
    question = presentations.get(f"obligation:{obligation_id}", "")
    title = titles.get(f"obligation:{obligation_id}", "")
    if not title:
        raise ValueError(
            f"historical obligation has no title_zh: {obligation_id}"
        )
    if existing is None and delta["from_state"] != "absent":
        projection.append({
            "obligation_id": obligation_id,
            "status": str(delta["from_state"]),
            "materiality": "",
            "title_zh": title,
            "epistemic_question": question,
            "requirement_refs": before,
            "detail_ref": "",
        })
    if delta["from_state"] == "absent":
        delta["obligation"] = {
            "obligation_id": obligation_id,
            "status": str(delta["to_state"]),
            "materiality": "",
            "title_zh": title,
            "epistemic_question": question,
            "requirement_refs": after,
            "detail_ref": "",
        }
    return delta


def _append_idempotent(
    *,
    operations: list[dict[str, Any]],
    components: dict[str, dict[str, Any]],
    operation: dict[str, Any],
) -> None:
    component_id = str(operation["component_id"])
    current = components.get(component_id)
    if current is None:
        operations.append(operation)
        components[component_id] = _component_from_operation(operation)
        return
    parent_id = str(operation.get("parent_id") or "")
    if str(current.get("parent_id") or "") != parent_id:
        operations.append({
            "op": "move",
            "component_id": component_id,
            "parent_id": parent_id,
        })
        current["parent_id"] = parent_id
    if _same_component(current, operation):
        return
    replacement = {
        **operation,
        "op": "replace",
        "kind": str(current["kind"]),
    }
    replacement.pop("parent_id", None)
    operations.append(replacement)
    current.update(_component_from_operation(operation))


def _same_component(
    current: dict[str, Any],
    desired: dict[str, Any],
) -> bool:
    return all(
        current.get(field) == desired.get(field)
        for field in ("title", "body", "content", "display_kind", "bindings")
    )


def _component_from_operation(
    operation: dict[str, Any],
) -> dict[str, Any]:
    return {
        "component_id": str(operation["component_id"]),
        "kind": str(operation["kind"]),
        "title": str(operation.get("title") or ""),
        "parent_id": str(operation.get("parent_id") or ""),
        "body": str(operation.get("body") or ""),
        "content": deepcopy(operation.get("content")),
        "display_kind": str(operation.get("display_kind") or ""),
        "bindings": deepcopy(operation.get("bindings") or []),
    }


def _retarget_bindings(
    bindings: list[dict[str, Any]],
    component_id: str,
) -> list[dict[str, Any]]:
    result = []
    for binding in bindings:
        value = deepcopy(binding)
        value["binding_id"] = (
            "reference-"
            + str(value["kind"]).replace("_", "-")
            + "-"
            + _digest(
                component_id,
                str(value["target_ref"]),
            )
        )
        result.append(value)
    return result


def _digest(*values: str) -> str:
    return hashlib.sha256("\x1f".join(values).encode()).hexdigest()[:48]
