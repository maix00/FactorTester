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
    component_ids: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    token = _token(str(event["event_id"]))
    lifecycle = event.get("evidence_lifecycle")
    lifecycle = lifecycle if isinstance(lifecycle, dict) else None
    identities = component_ids or {
        "special_id": f"obligation-changes-{token}",
        "change_table_id": f"obligation-change-table-{token}",
        "current_table_id": f"current-obligation-table-{token}",
        "requirement_table_id": f"obligation-requirement-table-{token}",
        **({
            "evidence_table_id": f"evidence-lifecycle-table-{token}",
        } if lifecycle is not None else {}),
    }
    required_ids = {
        "special_id", "change_table_id", "current_table_id",
        "requirement_table_id",
        *({"evidence_table_id"} if lifecycle is not None else set()),
    }
    if set(identities) != required_ids or any(
        not isinstance(identities[key], str) or not identities[key]
        for key in required_ids
    ):
        raise ValueError("obligation report component identities are invalid")
    special_id = identities["special_id"]
    change_table_id = identities["change_table_id"]
    current_table_id = identities["current_table_id"]
    requirement_table_id = identities["requirement_table_id"]
    deltas = event.get("obligation_delta") or []
    obligations = event.get("obligations_snapshot") or []
    evidence_uses = event.get("evidence_uses_snapshot") or []
    added_uses = _added_evidence_uses(event)
    coverage = event.get("coverage_snapshot") or []
    presentations = event.get("obligation_presentations") or {}
    obligation_titles = _obligation_titles(obligations)
    requirement_titles = _requirement_titles(
        coverage, event.get("requirement_titles"),
    )
    title = (
        "证据排除与义务变化"
        if (lifecycle or {}).get("action") == "exclude"
        else "证据恢复"
        if lifecycle is not None
        else "义务变化"
    )
    operations = [
        {
            "op": "add",
            "component_id": special_id,
            "kind": "special",
            "title": title,
            "parent_id": parent_id,
            "body": str(event.get("reason_markdown") or ""),
            "content": {
                "ledger_event_id": str(event["event_id"]),
                "ledger_sequence": int(event["sequence"]),
                "change_count": len(deltas),
                **({"evidence_lifecycle": lifecycle} if lifecycle else {}),
            },
            "display_kind": "obligation_changes",
            "bindings": [],
        },
        *(_evidence_lifecycle_operations(
            event=event,
            special_id=special_id,
            component_id=str(identities.get("evidence_table_id") or ""),
        ) if lifecycle is not None else []),
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
                    "证据", "证据使用理由",
                ],
                "rows": [
                    _change_row(
                        item,
                        presentations,
                        obligation_titles,
                        requirement_titles,
                        added_uses,
                    )
                    for item in deltas
                ],
            },
            "display_kind": "",
            "bindings": _obligation_bindings(
                event_id=str(event["event_id"]),
                owner_id=change_table_id,
                deltas=deltas,
                presentations=presentations,
                obligation_titles=obligation_titles,
            ) + _evidence_bindings(
                event_id=str(event["event_id"]),
                owner_id=change_table_id,
                evidence_uses=added_uses,
                role="obligation_change",
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
                obligations, presentations, requirement_titles,
                evidence_uses,
            ),
            "display_kind": "current_obligations",
            "bindings": _current_obligation_bindings(
                event_id=str(event["event_id"]),
                owner_id=current_table_id,
                obligations=obligations,
                presentations=presentations,
                requirement_titles=requirement_titles,
            ) + _evidence_bindings(
                event_id=str(event["event_id"]),
                owner_id=current_table_id,
                evidence_uses=evidence_uses,
                role="current_obligation",
            ),
        },
        {
            "op": "add",
            "component_id": requirement_table_id,
            "kind": "table",
            "title": "义务要求覆盖",
            "parent_id": special_id,
            "body": "",
            "content": _requirement_coverage_content(
                coverage, obligation_titles,
            ),
            "display_kind": "obligation_requirement_coverage",
            "bindings": _coverage_bindings(
                event_id=str(event["event_id"]),
                owner_id=requirement_table_id,
                coverage=coverage,
                obligation_titles=obligation_titles,
            ) + _evidence_bindings(
                event_id=str(event["event_id"]),
                owner_id=requirement_table_id,
                evidence_uses=evidence_uses,
                role="requirement_coverage",
            ),
        },
    ]
    return operations, dict(identities)


def _evidence_lifecycle_operations(
    *,
    event: dict[str, Any],
    special_id: str,
    component_id: str,
) -> list[dict[str, Any]]:
    lifecycle = event["evidence_lifecycle"]
    evidence_ref = str(lifecycle["evidence_ref"])
    title_zh = str(lifecycle["evidence_title_zh"])
    use = {
        "evidence_ref": evidence_ref,
        "evidence_title_zh": title_zh,
        "qualification": "",
        "rationale_zh": str(lifecycle["reason_zh"]),
    }
    removed = [
        item for item in event.get("evidence_use_delta") or []
        if isinstance(item, dict) and item.get("op") == "remove"
    ]
    return [{
        "op": "add",
        "component_id": component_id,
        "kind": "table",
        "title": "证据生命周期裁决",
        "parent_id": special_id,
        "body": "",
        "content": {
            "columns": [
                "证据", "原状态", "新状态", "解除覆盖关系", "裁决理由",
            ],
            "rows": [[
                _evidence_links([use]),
                str(lifecycle["from_status"]),
                str(lifecycle["to_status"]),
                str(len(removed)),
                str(lifecycle["reason_zh"]),
            ]],
        },
        "display_kind": "",
        "bindings": _evidence_bindings(
            event_id=str(event["event_id"]),
            owner_id=component_id,
            evidence_uses=[use],
            role="evidence_lifecycle",
        ),
    }]


def edge_coverage_operation(
    *,
    event_id: str,
    parent_id: str,
    coverage: list[dict[str, Any]],
    obligations: list[dict[str, Any]],
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
        "content": _requirement_coverage_content(
            coverage, _obligation_titles(obligations),
        ),
        "display_kind": "obligation_requirement_coverage",
        "bindings": _coverage_bindings(
            event_id=event_id,
            owner_id=component_id,
            coverage=coverage,
            obligation_titles=_obligation_titles(obligations),
        ) + _evidence_bindings(
            event_id=event_id,
            owner_id=component_id,
            evidence_uses=_coverage_evidence_uses(coverage),
            role="requirement_coverage",
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
                event.get("coverage_snapshot") or [],
                _obligation_titles(event.get("obligations_snapshot") or []),
            ),
            "display_kind": "",
            "bindings": _coverage_bindings(
                event_id=str(event["event_id"]),
                owner_id=table_id,
                coverage=event.get("coverage_snapshot") or [],
                obligation_titles=_obligation_titles(
                    event.get("obligations_snapshot") or []
                ),
            ) + _evidence_bindings(
                event_id=str(event["event_id"]),
                owner_id=table_id,
                evidence_uses=_coverage_evidence_uses(
                    event.get("coverage_snapshot") or []
                ),
                role="node_exit_coverage",
            ),
        },
    ]
    return operations, {"special_id": special_id, "table_id": table_id}


def _change_row(
    delta: dict[str, Any],
    presentations: dict[str, str],
    obligation_titles: dict[str, str],
    requirement_titles: dict[str, str],
    evidence_uses: list[dict[str, Any]],
) -> list[str]:
    obligation_id = str(delta["obligation_id"])
    obligation_ref = f"obligation:{obligation_id}"
    before = _refs(delta.get("from_requirement_refs"))
    after = _refs(delta.get("to_requirement_refs"))
    uses = [
        item for item in evidence_uses
        if item.get("obligation_ref") == obligation_ref
    ]
    return [
        typed_markdown_link(
            kind="obligation",
            target_ref=obligation_ref,
            label=_required_title(obligation_titles, obligation_ref),
        ),
        str(presentations.get(obligation_ref) or ""),
        _state(delta.get("from_state")),
        _state(delta.get("to_state")),
        "、".join(
            _requirement_link(item, requirement_titles)
            for item in after if item not in before
        ),
        "、".join(
            _requirement_link(item, requirement_titles)
            for item in before if item not in after
        ),
        _evidence_links(uses),
        "；".join(str(item.get("rationale_zh") or "") for item in uses),
    ]


def _current_obligations_content(
    obligations: list[dict[str, Any]],
    presentations: dict[str, str],
    requirement_titles: dict[str, str],
    evidence_uses: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "columns": [
            "研究义务", "问题", "当前状态", "当前覆盖义务小类", "证据",
        ],
        "rows": [
            [
                typed_markdown_link(
                    kind="obligation",
                    target_ref=f"obligation:{item['obligation_id']}",
                    label=_obligation_title(item),
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
                    _requirement_link(requirement_id, requirement_titles)
                    for requirement_id in _refs(
                        item.get("requirement_refs"),
                    )
                ),
                _evidence_links([
                    use for use in evidence_uses
                    if use.get("obligation_ref")
                    == f"obligation:{item['obligation_id']}"
                ]),
            ]
            for item in obligations
        ],
    }


def _requirement_coverage_content(
    rows: list[dict[str, Any]],
    obligation_titles: dict[str, str],
) -> dict[str, Any]:
    return {
        "columns": [
            "义务小类", "小类说明", "当前覆盖义务", "覆盖义务状态",
            "证据", "节点要求", "Edge 义务", "最低证据资格", "满足状态",
        ],
        "rows": [
            [
                _requirement_link(
                    str(row["requirement_id"]),
                    _requirement_titles(rows),
                ),
                str(row.get("description") or ""),
                "、".join(
                    typed_markdown_link(
                        kind="obligation", target_ref=str(reference),
                        label=_required_title(
                            obligation_titles, str(reference),
                        ),
                    )
                    for reference in row.get("obligation_refs") or []
                ),
                "、".join(
                    _state(value)
                    for value in row.get("obligation_statuses") or []
                ),
                _evidence_links(row.get("evidence_uses") or []),
                "是" if row.get("node_required", True) else "否",
                "是" if row.get("edge_required") else "否",
                f"`{row.get('minimum_qualification') or 'limited'}`",
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
    obligation_titles: dict[str, str],
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
            "label": _required_title(obligation_titles, obligation_ref),
            "data": {
                "title_zh": _required_title(
                    obligation_titles, obligation_ref,
                ),
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
    obligation_titles: dict[str, str],
) -> list[dict[str, Any]]:
    bindings = []
    seen_obligations: set[str] = set()
    requirement_titles = _requirement_titles(coverage)
    for row in coverage:
        requirement_id = str(row["requirement_id"])
        bindings.append({
            "binding_id": (
                "reference-requirement-"
                + _token(f"{event_id}:{owner_id}:{requirement_id}")
            ),
            "kind": "entry_requirement",
            "target_ref": f"requirement:{requirement_id}",
            "label": _required_title(requirement_titles, requirement_id),
            "data": {
                "title_zh": _required_title(
                    requirement_titles, requirement_id,
                ),
                "role": "obligation_coverage",
            },
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
                "label": _required_title(obligation_titles, reference),
                "data": {
                    "title_zh": _required_title(
                        obligation_titles, reference,
                    ),
                    "role": "requirement_coverage",
                },
            })
    return bindings


def _current_obligation_bindings(
    *,
    event_id: str,
    owner_id: str,
    obligations: list[dict[str, Any]],
    presentations: dict[str, str],
    requirement_titles: dict[str, str],
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
            "label": _obligation_title(item),
            "data": {
                "title_zh": _obligation_title(item),
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
                "label": _required_title(
                    requirement_titles, requirement_id,
                ),
                "data": {
                    "title_zh": _required_title(
                        requirement_titles, requirement_id,
                    ),
                    "role": "current_obligation_mapping",
                },
            })
    return bindings


def _added_evidence_uses(event: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item["use"]
        for item in event.get("evidence_use_delta") or []
        if (
            isinstance(item, dict)
            and item.get("op") == "add"
            and isinstance(item.get("use"), dict)
        )
    ]


def _evidence_links(evidence_uses: list[dict[str, Any]]) -> str:
    seen: set[str] = set()
    links = []
    for use in evidence_uses:
        reference = str(use.get("evidence_ref") or "")
        if not reference or reference in seen:
            continue
        seen.add(reference)
        links.append(typed_markdown_link(
            kind="evidence",
            target_ref=reference,
            label=str(use.get("evidence_title_zh") or reference),
        ))
    return "、".join(links)


def _evidence_bindings(
    *,
    event_id: str,
    owner_id: str,
    evidence_uses: list[dict[str, Any]],
    role: str,
) -> list[dict[str, Any]]:
    result = []
    seen: set[str] = set()
    for use in evidence_uses:
        reference = str(use.get("evidence_ref") or "")
        if not reference or reference in seen:
            continue
        seen.add(reference)
        title = str(use.get("evidence_title_zh") or "").strip()
        if not title:
            raise ValueError(f"Evidence has no title_zh: {reference}")
        result.append({
            "binding_id": (
                "reference-evidence-"
                + _token(f"{event_id}:{owner_id}:{reference}")
            ),
            "kind": "evidence",
            "target_ref": reference,
            "label": title,
            "data": {
                "title_zh": title,
                "qualification": str(use.get("qualification") or ""),
                "rationale_zh": str(use.get("rationale_zh") or ""),
                "role": role,
            },
        })
    return result


def _coverage_evidence_uses(
    coverage: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    values = []
    seen: set[str] = set()
    for row in coverage:
        for use in row.get("evidence_uses") or []:
            use_id = str(use.get("use_id") or "")
            if use_id and use_id not in seen:
                seen.add(use_id)
                values.append(use)
    return values


def _state(value: Any) -> str:
    key = str(value or "")
    return f"{_STATE_LABELS.get(key, '状态已更新')}（`{key}`）"


def _requirement_link(
    requirement_id: str,
    titles: dict[str, str],
) -> str:
    return typed_markdown_link(
        kind="entry_requirement",
        target_ref=f"requirement:{requirement_id}",
        label=_required_title(titles, requirement_id),
    )


def _obligation_titles(
    obligations: list[dict[str, Any]],
) -> dict[str, str]:
    return {
        f"obligation:{item['obligation_id']}": _obligation_title(item)
        for item in obligations
        if isinstance(item, dict) and item.get("obligation_id")
    }


def _obligation_title(item: dict[str, Any]) -> str:
    title = str(item.get("title_zh") or "").strip()
    if not title:
        raise ValueError(
            f"obligation {item.get('obligation_id') or ''} has no title_zh"
        )
    return title


def _requirement_titles(
    coverage: list[dict[str, Any]],
    historical_titles: Any = None,
) -> dict[str, str]:
    titles = {
        str(reference).removeprefix("requirement:"): str(title).strip()
        for reference, title in (
            historical_titles.items()
            if isinstance(historical_titles, dict) else []
        )
        if str(reference).strip() and str(title).strip()
    }
    titles.update({
        str(item["requirement_id"]): str(item.get("description") or "").strip()
        for item in coverage
        if isinstance(item, dict) and item.get("requirement_id")
    })
    return titles


def _required_title(titles: dict[str, str], reference: str) -> str:
    title = str(titles.get(reference) or "").strip()
    if not title:
        raise ValueError(f"reference has no title_zh: {reference}")
    return title


def _refs(value: Any) -> list[str]:
    return [
        str(item).removeprefix("requirement:")
        for item in value or []
    ]


def _token(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:24]
