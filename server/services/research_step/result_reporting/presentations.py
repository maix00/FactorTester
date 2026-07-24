"""Readable presentations projected from authoritative result objects."""

from __future__ import annotations

import sqlite3
from typing import Any

import orjson

from .metrics import metric_rows


def result_presentations(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    branch_id: str,
    rows: list[dict[str, Any]],
    receipt: dict[str, Any] | None,
) -> dict[str, dict[str, dict[str, str]]]:
    """Batch-project aliases without making the report or UI infer semantics."""
    obligation_refs = {
        _obligation_ref(item["obligation_id"])
        for item in ((receipt or {}).get("proposal") or {}).get(
            "obligation_delta"
        ) or []
    }
    obligations = _obligation_presentations(
        conn,
        instance_id=instance_id,
        branch_id=branch_id,
        obligation_refs=obligation_refs,
    )
    missing = obligation_refs.difference(obligations)
    if missing:
        raise ValueError(
            "authoritative obligation presentation is unavailable: "
            + ", ".join(sorted(missing))
        )
    return {
        "obligations": obligations,
        "evidence": {
            row["evidence_ref"]: _evidence_presentation(row)
            for row in rows
            if row.get("evidence_ref")
        },
    }


def _obligation_presentations(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    branch_id: str,
    obligation_refs: set[str],
) -> dict[str, dict[str, str]]:
    if not obligation_refs:
        return {}
    rows = conn.execute(
        """
        SELECT evidence_json
        FROM research_graph_trace
        WHERE instance_id=? AND branch_id=?
          AND json_type(evidence_json, '$.research_cycle_checkpoint')
              ='object'
        ORDER BY created_at DESC
        LIMIT 64
        """,
        (instance_id, branch_id),
    ).fetchall()
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        evidence = orjson.loads(str(row["evidence_json"]) or "{}")
        checkpoint = evidence.get("research_cycle_checkpoint") or {}
        for obligation in checkpoint.get("obligations") or []:
            if not isinstance(obligation, dict):
                continue
            reference = _obligation_ref(obligation.get("obligation_id"))
            question = str(obligation.get("epistemic_question") or "").strip()
            if reference in obligation_refs and question and reference not in result:
                result[reference] = {"alias_zh": question[:240]}
        if obligation_refs.issubset(result):
            break
    return result


def _evidence_presentation(row: dict[str, Any]) -> dict[str, str]:
    scope = _scope_alias(row.get("run_spec_alias_zh"))
    label = f"{scope} · {_analysis_alias(row.get('kind'))} 结果"
    metrics = _summary_metrics(row)
    summary = "；".join(
        f"{_short_metric_label(metric)} {value}" for metric, value in metrics
    )
    return {
        "alias_zh": label[:160],
        "summary_zh": summary[:240],
    }


def _summary_metrics(row: dict[str, Any]) -> list[tuple[str, str]]:
    metrics = metric_rows(row)
    priorities = (
        ("IC 均值", "t 统计量", "信息比率")
        if row.get("kind") == "ic"
        else ("夏普比率", "最大回撤", "年化收益率")
    )
    selected = [
        item for keyword in priorities
        for item in metrics if keyword in item[0]
    ]
    return (selected or metrics)[:3]


def _short_metric_label(value: str) -> str:
    parts = value.split(" · ")
    if parts and parts[0] in {
        "IC 均值", "IC 标准差", "信息比率", "t 统计量",
    }:
        return parts[0]
    return value


def _obligation_ref(value: Any) -> str:
    identifier = str(value or "").removeprefix("obligation:")
    return f"obligation:{identifier}" if identifier else ""


def _analysis_alias(value: Any) -> str:
    return {
        "ic": "截面 IC",
        "backtest": "回测",
        "factor_evaluation": "因子评价",
        "robustness": "稳健性检验",
    }.get(str(value or ""), "研究检验")


def _scope_alias(value: Any) -> str:
    alias = str(value or "")
    if "夜盘" in alias:
        return "夜盘"
    if "日盘" in alias:
        return "日盘"
    return "既定运行范围"
