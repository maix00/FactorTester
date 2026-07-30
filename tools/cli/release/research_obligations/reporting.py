"""Structured report operations derived from obligation ledger events."""

from __future__ import annotations

import hashlib
from typing import Any

from tools.cli.release.research_reporting.authoring.inline_links import (
    typed_markdown_link,
)


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
    *,
    event: dict[str, Any],
    parent_id: str,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    token = _token(str(event["event_id"]))
    special_id = f"obligation-changes-{token}"
    change_table_id = f"obligation-change-table-{token}"
    current_table_id = f"current-obligation-table-{token}"
    requirement_table_id = f"obligation-requirement-table-{token}"
    deltas = event.get("obligation_delta") or []
    obligations = event.get("obligations_snapshot") or []
    coverage = event.get("coverage_snapshot") or []
    presentations = event.get("obligation_presentations") or {}
    operations = [
        {
            "op": "add",
            "component_id": special_id,
            "kind": "special",
            "title": "义务变化",
            "parent_id": parent_id,
            "body": str(event.get("reason_markdown") or ""),
            "content": {
                "ledger_event_id": str(event["event_id"]),
                "ledger_sequence": int(event["sequence"]),
                "change_count": len(deltas),
            },
            "display_kind": "obligation_changes",
            "bindings": [],
        },
        {
            "op": "add",
            "component_id": change_table_id,
            "kind": "table",
            "title": "义务变化",
            "parent_id": special_id,
            "body": "",
            "content": {
                "columns": [
                    "研究义务", "问题", "原状态", "新状态",
                    "新增覆盖小类", "移除覆盖小类",
                ],
                "rows": [
                    _change_row(item, presentations) for item in deltas
                ],
            },
            "display_kind": "",
            "bindings": _obligation_bindings(
                event_id=str(event["event_id"]),
                owner_id=change_table_id,
                deltas=deltas,
                presentations=presentations,
            ),
        },
        {
            "op": "add",
            "component_id": current_table_id,
            "kind": "table",
            "title": "当前义务清单",
            "parent_id": special_id,
            "body": "",
            "content": _current_obligations_content(
                obligations, presentations,
            ),
            "display_kind": "current_obligations",
            "bindings": _current_obligation_bindings(
                event_id=str(event["event_id"]),
                owner_id=current_table_id,
                obligations=obligations,
                presentations=presentations,
            ),
        },
        {
            "op": "add",
            "component_id": requirement_table_id,
            "kind": "table",
            "title": "义务要求覆盖",
            "parent_id": special_id,
            "body": "",
            "content": _requirement_coverage_content(coverage),
            "display_kind": "obligation_requirement_coverage",
            "bindings": _coverage_bindings(
                event_id=str(event["event_id"]),
                owner_id=requirement_table_id,
                coverage=coverage,
            ),
        },
    ]
    return operations, {
        "special_id": special_id,
        "change_table_id": change_table_id,
        "current_table_id": current_table_id,
        "requirement_table_id": requirement_table_id,
    }


def edge_coverage_operation(
    *,
    event_id: str,
    parent_id: str,
    coverage: list[dict[str, Any]],
    replace: bool,
) -> tuple[dict[str, Any], str]:
    component_id = f"obligation-requirement-table-{_token(event_id)}"
    return {
        "op": "replace" if replace else "add",
        "component_id": component_id,
        **({} if replace else {
            "kind": "table",
            "parent_id": parent_id,
        }),
        "title": "义务要求覆盖",
        "body": "",
        "content": _requirement_coverage_content(coverage),
        "display_kind": "obligation_requirement_coverage",
        "bindings": _coverage_bindings(
            event_id=event_id,
            owner_id=component_id,
            coverage=coverage,
        ),
    }, component_id


def edge_selection_operation(
    *,
    event: dict[str, Any],
    parent_id: str,
    bindings: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], str]:
    token = _token(str(event["event_id"]))
    component_id = f"path-selection-{token}"
    edge_id = str(event.get("edge_id") or "")
    target_node = str(event.get("target_node") or "")
    operation = {
        "op": "add",
        "component_id": component_id,
        "kind": "special",
        "title": "研究路径选择",
        "parent_id": parent_id,
        "body": str(event.get("reason_markdown") or ""),
        "content": {
            "ledger_event_id": str(event["event_id"]),
            "ledger_sequence": int(event["sequence"]),
            "edge_id": edge_id,
            "target_node": target_node,
            "state_ref": str(event.get("state_ref") or ""),
        },
        "display_kind": "path_selection",
        "bindings": list(bindings or []),
    }
    return operation, component_id


def node_exit_operations(
    *,
    event: dict[str, Any],
    parent_id: str,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    token = _token(str(event["event_id"]))
    special_id = f"node-exit-obligation-coverage-{token}"
    table_id = f"node-exit-obligation-table-{token}"
    receipt = event.get("receipt") or {}
    operations = [
        {
            "op": "add",
            "component_id": special_id,
            "kind": "special",
            "title": "节点离开义务覆盖",
            "parent_id": parent_id,
            "body": (
                f"沿 `{event.get('edge_id', '')}` 进入 "
                f"`{event.get('target_node', '')}`"
            ),
            "content": {
                "coverage_hash": str(event.get("coverage_hash") or ""),
                "server_trace_ref": str(receipt.get("trace_ref") or ""),
                "server_checkpoint_ref": str(
                    receipt.get("checkpoint_ref") or ""
                ),
            },
            "display_kind": "obligation_coverage",
            "bindings": [],
        },
        {
            "op": "add",
            "component_id": table_id,
            "kind": "table",
            "title": "精确提交的覆盖清单",
            "parent_id": special_id,
            "body": "",
            "content": _requirement_coverage_content(
                event.get("coverage_snapshot") or []
            ),
            "display_kind": "",
            "bindings": _coverage_bindings(
                event_id=str(event["event_id"]),
                owner_id=table_id,
                coverage=event.get("coverage_snapshot") or [],
            ),
        },
    ]
    return operations, {"special_id": special_id, "table_id": table_id}


def _change_row(
    delta: dict[str, Any],
    presentations: dict[str, str],
) -> list[str]:
    obligation_id = str(delta["obligation_id"])
    obligation_ref = f"obligation:{obligation_id}"
    before = _refs(delta.get("from_requirement_refs"))
    after = _refs(delta.get("to_requirement_refs"))
    return [
        typed_markdown_link(
            kind="obligation", target_ref=obligation_ref, label=obligation_id,
        ),
        str(presentations.get(obligation_ref) or ""),
        _state(delta.get("from_state")),
        _state(delta.get("to_state")),
        "、".join(_requirement_link(item) for item in after if item not in before),
        "、".join(_requirement_link(item) for item in before if item not in after),
    ]


def _current_obligations_content(
    obligations: list[dict[str, Any]],
    presentations: dict[str, str],
) -> dict[str, Any]:
    return {
        "columns": [
            "研究义务", "问题", "当前状态", "当前覆盖义务小类",
        ],
        "rows": [
            [
                typed_markdown_link(
                    kind="obligation",
                    target_ref=f"obligation:{item['obligation_id']}",
                    label=str(item["obligation_id"]),
                ),
                str(
                    presentations.get(
                        f"obligation:{item['obligation_id']}",
                    )
                    or item.get("epistemic_question")
                    or item.get("question_summary")
                    or ""
                ),
                _state(item.get("status")),
                "、".join(
                    _requirement_link(requirement_id)
                    for requirement_id in _refs(
                        item.get("requirement_refs"),
                    )
                ),
            ]
            for item in obligations
        ],
    }


def _requirement_coverage_content(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "columns": [
            "义务小类", "小类说明", "当前覆盖义务", "覆盖义务状态",
            "节点要求", "Edge 义务", "满足状态",
        ],
        "rows": [
            [
                _requirement_link(str(row["requirement_id"])),
                str(row.get("description") or ""),
                "、".join(
                    typed_markdown_link(
                        kind="obligation", target_ref=str(reference),
                        label=str(reference).removeprefix("obligation:"),
                    )
                    for reference in row.get("obligation_refs") or []
                ),
                "、".join(
                    _state(value)
                    for value in row.get("obligation_statuses") or []
                ),
                "是" if row.get("node_required", True) else "否",
                "是" if row.get("edge_required") else "否",
                f"`{row.get('satisfaction') or 'pending'}`",
            ]
            for row in rows
        ],
    }


def _obligation_bindings(
    *,
    event_id: str,
    owner_id: str,
    deltas: list[dict[str, Any]],
    presentations: dict[str, str],
) -> list[dict[str, Any]]:
    bindings = []
    for delta in deltas:
        obligation_id = str(delta["obligation_id"])
        obligation_ref = f"obligation:{obligation_id}"
        bindings.append({
            "binding_id": (
                "reference-obligation-"
                + _token(f"{event_id}:{owner_id}:{obligation_ref}")
            ),
            "kind": "obligation",
            "target_ref": obligation_ref,
            "label": obligation_id,
            "data": {
                "question_summary": str(
                    presentations.get(obligation_ref) or ""
                ),
            },
        })
    return bindings


def _coverage_bindings(
    *,
    event_id: str,
    owner_id: str,
    coverage: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    bindings = []
    seen_obligations: set[str] = set()
    for row in coverage:
        requirement_id = str(row["requirement_id"])
        bindings.append({
            "binding_id": (
                "reference-requirement-"
                + _token(f"{event_id}:{owner_id}:{requirement_id}")
            ),
            "kind": "entry_requirement",
            "target_ref": f"requirement:{requirement_id}",
            "label": requirement_id,
            "data": {"role": "obligation_coverage"},
        })
        for obligation_ref in row.get("obligation_refs") or []:
            reference = str(obligation_ref)
            if reference in seen_obligations:
                continue
            seen_obligations.add(reference)
            bindings.append({
                "binding_id": (
                    "reference-obligation-"
                    + _token(f"{event_id}:{owner_id}:{reference}")
                ),
                "kind": "obligation",
                "target_ref": reference,
                "label": reference.removeprefix("obligation:"),
                "data": {"role": "requirement_coverage"},
            })
    return bindings


def _current_obligation_bindings(
    *,
    event_id: str,
    owner_id: str,
    obligations: list[dict[str, Any]],
    presentations: dict[str, str],
) -> list[dict[str, Any]]:
    bindings = []
    seen_requirements: set[str] = set()
    for item in obligations:
        obligation_id = str(item["obligation_id"])
        obligation_ref = f"obligation:{obligation_id}"
        bindings.append({
            "binding_id": (
                "reference-obligation-"
                + _token(f"{event_id}:{owner_id}:{obligation_ref}")
            ),
            "kind": "obligation",
            "target_ref": obligation_ref,
            "label": obligation_id,
            "data": {
                "question_summary": str(
                    presentations.get(obligation_ref)
                    or item.get("epistemic_question")
                    or item.get("question_summary")
                    or ""
                ),
                "role": "current_obligation",
            },
        })
        for requirement_id in _refs(item.get("requirement_refs")):
            if requirement_id in seen_requirements:
                continue
            seen_requirements.add(requirement_id)
            bindings.append({
                "binding_id": (
                    "reference-requirement-"
                    + _token(f"{event_id}:{owner_id}:{requirement_id}")
                ),
                "kind": "entry_requirement",
                "target_ref": f"requirement:{requirement_id}",
                "label": requirement_id,
                "data": {"role": "current_obligation_mapping"},
            })
    return bindings


def _state(value: Any) -> str:
    key = str(value or "")
    return f"{_STATE_LABELS.get(key, '状态已更新')}（`{key}`）"


def _requirement_link(requirement_id: str) -> str:
    return typed_markdown_link(
        kind="entry_requirement",
        target_ref=f"requirement:{requirement_id}",
        label=requirement_id,
    )


def _refs(value: Any) -> list[str]:
    return [
        str(item).removeprefix("requirement:")
        for item in value or []
    ]


def _token(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:24]
