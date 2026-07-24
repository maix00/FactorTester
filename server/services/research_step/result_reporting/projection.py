"""Bounded Chinese report items for one audited Evidence Action."""

from __future__ import annotations
from typing import Any

from tools.cli.release.research_reporting.report_items import (
    report_fragment_hash, report_item_hash,
)
from .metrics import metric_rows


def build_result_report_projection(
    *, action: dict[str, Any], plan_hash: str,
    rows: list[dict[str, Any]], receipt: dict[str, Any] | None,
) -> dict[str, Any]:
    action_id = str(action["action_id"])
    result_links = _result_links(rows)
    audit_links = _audit_links(action, plan_hash, receipt)
    local = [
        _item(
            "report.node.trial_execution.action", f"action:{action_id}",
            f"试验结果 · {_action_alias(action_id)}", "table",
            _result_table(rows), result_links,
        ),
        _item(
            "report.node.trial_execution.action", f"audit:{action_id}",
            f"审计与义务变化 · {_action_alias(action_id)}", "list",
            _audit_list(receipt, audit_links), audit_links,
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


def _audit_links(action, plan_hash, receipt):
    values = [{
        "link_id": "trial-plan", "kind": "trial_plan",
        "target_ref": f"trial-plan:sha256:{plan_hash}",
        "label": "当前试验计划",
    }]
    for index, ref in enumerate(action.get("output_evidence_refs") or [], 1):
        values.append({
            "link_id": f"evidence-{index}", "kind": "evidence",
            "target_ref": str(ref), "label": f"JobAttempt 证据 · {index}",
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
    for index, obligation_id in enumerate(normalized_ids, 1):
        values.append({
            "link_id": f"obligation-{index}", "kind": "obligation",
            "target_ref": f"obligation:{obligation_id}",
            "label": _obligation_alias(obligation_id),
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


def _audit_list(receipt, links):
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
            f"审计结论：{decision['disposition']}；"
            f"后续路径：{proposal['recommended_action']}。"
        ),
        "link_ids": [
            "trial-plan",
            *[item["link_id"] for item in links if item["kind"] == "evidence"],
        ],
    }]
    by_ref = {item["target_ref"]: item["link_id"] for item in links}
    for delta in proposal.get("obligation_delta") or []:
        obligation_id = str(delta["obligation_id"]).removeprefix("obligation:")
        ref = f"obligation:{obligation_id}"
        rows.append({
            "text": (
                f"{_obligation_alias(obligation_id)}："
                f"{delta.get('from_state')} → {delta.get('to_state')}；"
                f"判定标准：{delta['criterion_ref']}"
            )[:500],
            "link_ids": [by_ref[ref]] if ref in by_ref else [],
        })
    return {"kind": "list", "rows": rows}


def _obligation_alias(value):
    aliases = {
        "predictive-validity": "预测有效性义务",
        "cost-survival": "交易成本后存活义务",
        "out-of-sample": "样本外有效性义务",
        "data-availability": "数据可用性义务",
    }
    return aliases.get(value, "研究义务（点击查看完整定义）")


def _action_alias(value):
    text = str(value or "").lower()
    if "ic" in text:
        return "样本内 IC 检验"
    if any(key in text for key in ("historical-fee", "fee-aware", "net")):
        return "历史手续费回测"
    if any(key in text for key in ("gross", "no-fee", "fee-free")):
        return "无手续费回测"
    if "backtest" in text:
        return "回测检验"
    return "当前证据检验"


def _analysis_alias(value):
    return {
        "ic": "截面 IC 检验",
        "backtest": "策略回测",
        "factor_evaluation": "因子评价",
        "robustness": "稳健性检验",
    }.get(str(value or ""), "研究检验")


def _role_alias(value):
    return {
        "candidate": "候选方案",
        "baseline": "基准方案",
        "control": "对照方案",
        "primary": "主要方案",
    }.get(str(value or ""), "试验方案")


def _status_alias(value):
    return {
        "succeeded": "已成功",
        "failed": "失败",
        "cancelled": "已取消",
        "running": "运行中",
    }.get(str(value or ""), "状态已记录")


def _scope_alias(row):
    alias = str(row.get("run_spec_alias_zh") or "")
    if "夜盘" in alias:
        return "夜盘"
    if "日盘" in alias:
        return "日盘"
    return "既定产品范围"
