"""Bounded Chinese report items for one audited Evidence Action."""

from __future__ import annotations
from typing import Any

from tools.cli.release.research_reporting.report_items import (
    report_fragment_hash, report_item_hash,
)
from .labels import (
    action_alias as _action_alias,
    analysis_alias as _analysis_alias,
    criterion_alias as _criterion_alias,
    disposition_alias as _disposition_alias,
    obligation_alias as _obligation_alias,
    obligation_state_alias as _obligation_state_alias,
    role_alias as _role_alias,
    route_alias as _route_alias,
    scope_alias as _scope_alias,
    status_alias as _status_alias,
)
from .metrics import metric_rows


def build_result_report_projection(
    *, action: dict[str, Any], plan_hash: str,
    rows: list[dict[str, Any]], receipt: dict[str, Any] | None,
    presentations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    presentations = presentations or {}
    action_id = _action_ref(action["action_id"])
    action_key = action_id.removeprefix("action:")
    result_links = _result_links(rows)
    audit_links = _audit_links(
        action, plan_hash, receipt, presentations=presentations,
    )
    local = [
        _item(
            "report.node.trial_execution.action", action_id,
            f"试验结果 · {_action_alias(action_id)}", "table",
            _result_table(rows), result_links,
        ),
        _item(
            "report.node.trial_execution.action", f"audit:{action_key}",
            f"审计与义务变化 · {_action_alias(action_id)}", "list",
            _audit_list(
                receipt, audit_links, presentations=presentations,
            ),
            audit_links,
        ),
    ]
    compact = [{
        key: item[key] for key in (
            "report_requirement_id", "subject_ref", "content_kind", "item_hash",
        )
    } for item in local]
    return {
        "schema_version": 1,
        "action_id": action_id,
        "report_submission": {
            "schema_version": 1,
            "fragment_hash": report_fragment_hash(compact),
            "items": compact,
        },
        "local_report_items": local,
    }


def _action_ref(value):
    key = str(value or "").strip()
    while key.startswith("action:"):
        key = key.removeprefix("action:")
    if not key:
        raise ValueError("Evidence Action ID is empty")
    return f"action:{key}"


def _item(requirement, subject, title, kind, content, links):
    binding = {"report_requirement_id": requirement, "subject_ref": subject}
    return {
        **binding, "title_zh": title, "content_kind": kind,
        "item_hash": report_item_hash(
            **binding, content_kind=kind, content=content,
        ),
        "content": content, "content_zh": [title], "links": links,
        "report_binding": binding, "chapter_ref": "node:trial_execution",
    }


def _result_links(rows):
    values = []
    for index, row in enumerate(rows, 1):
        alias = str(row.get("run_spec_alias_zh") or "既定试验范围")
        for field, kind, prefix, label in (
            ("run_spec_hash", "run_spec", "runspec:", f"运行前配置 · {alias}"),
            ("run_id", "run", "run:", f"冻结运行配置 · {alias}"),
            (
                "job_id", "job", "job:",
                f"计算任务 · {_analysis_alias(row['kind'])}",
            ),
        ):
            value = str(row.get(field) or "")
            if value:
                values.append({
                    "link_id": f"{kind}-{index}", "kind": kind,
                    "target_ref": prefix + value, "label": label,
                })
    return values


def _audit_links(action, plan_hash, receipt, *, presentations):
    values = [{
        "link_id": "trial-plan", "kind": "trial_plan",
        "target_ref": f"trial-plan:sha256:{plan_hash}",
        "label": "当前试验计划",
    }]
    evidence_presentations = presentations.get("evidence") or {}
    for index, ref in enumerate(action.get("output_evidence_refs") or [], 1):
        presentation = evidence_presentations.get(str(ref)) or {}
        label = str(presentation.get("alias_zh") or "结果证据")
        summary = str(presentation.get("summary_zh") or "")
        values.append({
            "link_id": f"evidence-{index}", "kind": "evidence",
            "target_ref": str(ref),
            "label": f"{label} · {summary}"[:160] if summary else label[:160],
        })
    obligation_ids = (
        [
            item["obligation_id"]
            for item in receipt["proposal"].get("obligation_delta") or []
        ]
        if receipt else []
    )
    normalized_ids = dict.fromkeys(
        str(raw).removeprefix("obligation:") for raw in obligation_ids
    )
    obligation_presentations = presentations.get("obligations") or {}
    for index, obligation_id in enumerate(normalized_ids, 1):
        reference = f"obligation:{obligation_id}"
        presentation = obligation_presentations.get(reference) or {}
        values.append({
            "link_id": f"obligation-{index}", "kind": "obligation",
            "target_ref": reference,
            "label": _obligation_alias(
                obligation_id, presentation=presentation,
            ),
        })
    return values


def _result_table(rows):
    values = []
    for row in rows:
        metrics = metric_rows(row)
        for label, value in metrics:
            values.append({
                "cells": [
                    _analysis_alias(row["kind"]),
                    _role_alias(row["trial_role"]),
                    _status_alias(row["status"]),
                    _scope_alias(row),
                    label,
                    value,
                ],
                "link_ids": [
                    f"run_spec-{row['index']}",
                    f"run-{row['index']}", f"job-{row['index']}",
                ],
            })
    kinds = {row["kind"] for row in rows}
    result_kind = next(iter(kinds)) if len(kinds) == 1 else "factor_evaluation"
    if result_kind not in {"ic", "backtest", "factor_evaluation", "robustness"}:
        result_kind = "factor_evaluation"
    return {
        "kind": "table", "result_kind": result_kind,
        "columns": [
            "分析", "试验角色", "状态", "运行范围", "指标", "值",
        ],
        "rows": values,
    }


def _audit_list(receipt, links, *, presentations):
    if receipt is None:
        return {"kind": "list", "rows": [{
            "text": (
                "旧版检查点未保留完整裁决，义务变化不可恢复；"
                "TrialPlan 与结果证据引用仍保留供审计。"
            ),
            "link_ids": [item["link_id"] for item in links],
        }]}
    proposal, decision = receipt["proposal"], receipt["decision"]
    rows = [{
        "text": (
            f"审计结论：{_disposition_alias(decision['disposition'])}；"
            f"后续路径：{_route_alias(proposal['recommended_action'])}。"
        ),
        "link_ids": [
            "trial-plan",
            *[item["link_id"] for item in links if item["kind"] == "evidence"],
        ],
    }]
    by_ref = {item["target_ref"]: item["link_id"] for item in links}
    obligation_presentations = presentations.get("obligations") or {}
    for delta in proposal.get("obligation_delta") or []:
        obligation_id = str(delta["obligation_id"]).removeprefix("obligation:")
        ref = f"obligation:{obligation_id}"
        rows.append({
            "text": (
                f"{_obligation_alias(obligation_id, presentation=obligation_presentations.get(ref))}："
                f"{_obligation_state_alias(delta.get('from_state'))} → "
                f"{_obligation_state_alias(delta.get('to_state'))}；"
                f"判定标准：{_criterion_alias(delta['criterion_ref'])}"
            )[:500],
            "link_ids": [by_ref[ref]] if ref in by_ref else [],
        })
    return {"kind": "list", "rows": rows}
