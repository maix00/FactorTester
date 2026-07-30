"""Rebuild obligation-change report sections from persisted Graph history."""

from __future__ import annotations

import hashlib
from typing import Any

from tools.cli.release.research_reporting.authoring.inline_links import (
    typed_markdown_link,
)
from tools.cli.release.research_reporting.node_titles import node_title_zh


_STATE_LABELS = {
    "absent": "尚未建立",
    "bounded": "已限定",
    "discharged": "已解除",
    "open": "待处理",
    "rejected": "已否决",
    "reopened": "已重开",
    "serviced": "本轮已处理",
}


def obligation_change_operations(
    contexts: list[dict[str, Any]],
    *,
    parent_by_step: dict[str, str],
    component_ids: set[str],
    component_parents: dict[str, str],
    binding_ids: set[str],
) -> tuple[list[dict[str, Any]], int]:
    """Return idempotent system operations and the number of change episodes."""
    operations: list[dict[str, Any]] = []
    episodes = 0
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
        token = _digest(step_ref)
        special_id = f"obligation-changes-{token}"
        table_id = f"obligation-change-table-{token}"
        presentations = {
            str(item["obligation_ref"]): str(item["question_summary"])
            for item in context.get("obligation_presentations") or []
        }
        bindings = _bindings(
            step_ref, changes, presentations, binding_ids,
        )
        if special_id not in component_ids:
            operations.append({
                "op": "add",
                "component_id": special_id,
                "kind": "special",
                "title": (
                    f"{node_title_zh(str(context['from_node']))} → "
                    f"{node_title_zh(str(context['to_node']))}"
                ),
                "parent_id": parent_id,
                "body": f"该研究图转换改变了 {len(changes)} 项研究义务",
                "content": {
                    "step_ref": step_ref,
                    "change_count": len(changes),
                },
                "display_kind": "obligation_changes",
                "bindings": bindings,
            })
            component_ids.add(special_id)
            binding_ids.update(
                item["binding_id"] for item in bindings
            )
        else:
            if component_parents.get(special_id) != parent_id:
                operations.append({
                    "op": "move",
                    "component_id": special_id,
                    "parent_id": parent_id,
                })
                component_parents[special_id] = parent_id
            for binding in bindings:
                if binding["binding_id"] not in binding_ids:
                    operations.append({
                        "op": "bind",
                        "component_id": special_id,
                        "binding": binding,
                    })
                    binding_ids.add(binding["binding_id"])
        if table_id not in component_ids:
            operations.append({
                "op": "add",
                "component_id": table_id,
                "kind": "table",
                "title": "义务状态变更",
                "parent_id": special_id,
                "body": "",
                "content": {
                    "columns": [
                        "研究义务", "问题", "原状态", "新状态", "约束变化",
                    ],
                    "rows": [
                        _row(item, presentations)
                        for item in changes
                    ],
                },
                "display_kind": "",
                "bindings": [],
            })
            component_ids.add(table_id)
    return operations, episodes


def _bindings(
    step_ref: str,
    changes: list[dict[str, Any]],
    presentations: dict[str, str],
    existing: set[str],
) -> list[dict[str, Any]]:
    result = []
    for change in changes:
        obligation_id = str(change["obligation_id"])
        target = f"obligation:{obligation_id}"
        binding_id = f"obligation-change-{_digest(step_ref, target)}"
        if binding_id in existing:
            continue
        result.append({
            "binding_id": binding_id,
            "kind": "obligation",
            "target_ref": target,
            "label": obligation_id,
            "data": {
                "step_ref": step_ref,
                "question_summary": presentations.get(target, ""),
                "from_state": str(change["from_state"]),
                "to_state": str(change["to_state"]),
            },
        })
        existing.add(binding_id)
    return result


def _row(
    change: dict[str, Any],
    presentations: dict[str, str],
) -> list[str]:
    obligation_id = str(change["obligation_id"])
    target = f"obligation:{obligation_id}"
    return [
        typed_markdown_link(
            kind="obligation",
            target_ref=target,
            label=obligation_id,
        ),
        presentations.get(target, ""),
        _state(change["from_state"]),
        _state(change["to_state"]),
        _requirements(change),
    ]


def _state(value: Any) -> str:
    key = str(value)
    return f"{_STATE_LABELS.get(key, '状态已更新')}（`{key}`）"


def _requirements(change: dict[str, Any]) -> str:
    before = [str(item) for item in change.get("from_requirement_refs") or []]
    after = [str(item) for item in change.get("to_requirement_refs") or []]
    if before == after:
        return "—"
    added = [item for item in after if item not in before]
    removed = [item for item in before if item not in after]
    parts = []
    if added:
        parts.append("新增 " + "、".join(f"`{item}`" for item in added))
    if removed:
        parts.append("移除 " + "、".join(f"`{item}`" for item in removed))
    return "；".join(parts) or "要求集合已调整"


def _digest(*values: str) -> str:
    return hashlib.sha256("\x1f".join(values).encode()).hexdigest()[:48]
