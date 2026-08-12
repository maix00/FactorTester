"""Compact margin-budget projections for CLI step output."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import click

from .values import scalar, table_from_mappings


_FIELDS = (
    ("equity", "权益"),
    ("target_margin", "目标保证金"),
    ("projected_margin", "预计保证金"),
    ("weighted_margin_ratio", "加权保证金率"),
    ("scale", "目标缩放倍数"),
    ("execution_scale", "执行缩放倍数"),
    ("gross_leverage", "总名义杠杆"),
    ("projected_utilization", "预计保证金利用率"),
    ("max_utilization", "保证金硬上限"),
    ("rounding_error", "取整误差"),
    ("hard_limit_headroom", "硬上限余量"),
)


def render_rows(field: str, rows: list[Mapping[str, Any]], *, indent: str) -> list[str] | None:
    if not field.endswith((".margin_budget_summary", ".execution_margin_summary")):
        return None
    pools = _pool_rows(rows)
    if not pools:
        return []
    if len(pools) == 1:
        pool = pools[0]
        body = [{"指标": "现金池", "数值": pool["cash_pool"]}]
        body.extend(
            {"指标": label, "数值": scalar(pool[key])}
            for key, label in _FIELDS if key in pool
        )
        lines = table_from_mappings(body, indent=indent)
    else:
        primary = [{
            "cash_pool": row["cash_pool"],
            "equity": row.get("equity"),
            "target_margin": row.get("target_margin"),
            "projected_margin": row.get("projected_margin"),
            "utilization": row.get("projected_utilization"),
            "max": row.get("max_utilization"),
        } for row in pools]
        leverage = [{
            "cash_pool": row["cash_pool"],
            "weighted_margin_ratio": row.get("weighted_margin_ratio"),
            "target_scale": row.get("scale"),
            "execution_scale": row.get("execution_scale"),
            "gross_leverage": row.get("gross_leverage"),
            "rounding_error": row.get("rounding_error"),
            "headroom": row.get("hard_limit_headroom"),
        } for row in pools]
        lines = [
            *table_from_mappings(primary, indent=indent),
            *table_from_mappings(leverage, indent=indent),
        ]
    return [
        *lines,
        click.style(f"{indent}完整保证金预算 decision 请使用 job step-field 查看。", dim=True),
    ]


def _pool_rows(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        value = row.get("after", row.get("value"))
        if not isinstance(value, Mapping):
            return []
        for pool_id, summary in value.items():
            if not isinstance(summary, Mapping):
                return []
            result.append({"cash_pool": str(pool_id), **dict(summary)})
    return result
