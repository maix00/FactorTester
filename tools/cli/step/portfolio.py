"""Portfolio weight and quantity-map projections."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import click

from .values import route_label, scalar, table_from_mappings


MAP_FIELDS = (".target_weights", ".raw_deltas", ".sized_deltas", ".deltas", ".signal_value")


def render_rows(field: str, rows: list[Mapping[str, Any]], *, indent: str) -> list[str] | None:
    if field.endswith(".trade_intent"):
        return _trade_intents(rows, indent=indent)
    if not field.endswith(MAP_FIELDS):
        return None
    if field.endswith(".signal_value"):
        if any(isinstance(row.get("after", row.get("value")), Mapping)
               and "type" in row.get("after", row.get("value")) for row in rows):
            return None
        return _signal_summary(rows, indent=indent)
    if field.endswith((".raw_deltas", ".sized_deltas", ".deltas")):
        return _delta_summary(rows, indent=indent)
    result = []
    omitted_zero = 0
    omit_zero = field.endswith((".raw_deltas", ".sized_deltas", ".deltas"))
    for row in rows:
        value = row.get("after", row.get("value"))
        if not isinstance(value, Mapping) or not all(not isinstance(item, Mapping) for item in value.values()):
            return None
        owner = str(row.get("strategy") or route_label(row))
        for instrument, item in value.items():
            if omit_zero and item == 0:
                omitted_zero += 1
                continue
            result.append({"owner": owner, "instrument": instrument, "value": scalar(item)})
    lines = table_from_mappings(result, indent=indent)
    if omitted_zero:
        lines.append(click.style(
            f"{indent}已省略 {omitted_zero} 个零 delta；job step-field 可查看完整映射。",
            dim=True,
        ))
    return lines


def _delta_summary(rows: list[Mapping[str, Any]], *, indent: str) -> list[str] | None:
    result = []
    zero_count = 0
    for row in rows:
        value = row.get("after", row.get("value"))
        if not isinstance(value, Mapping) or not all(isinstance(item, (int, float)) for item in value.values()):
            return None
        nonzero = [float(item) for item in value.values() if item != 0]
        zero_count += len(value) - len(nonzero)
        result.append({
            "owner": str(row.get("strategy") or route_label(row)),
            "instruments": len(nonzero),
            "buy": sum(item > 0 for item in nonzero),
            "sell": sum(item < 0 for item in nonzero),
            "gross_abs": sum(abs(item) for item in nonzero),
            "min": min(nonzero, default=None),
            "max": max(nonzero, default=None),
        })
    note = f"逐品种 delta 请使用 job step-field 查看；已省略 {zero_count} 个零 delta。"
    return [*table_from_mappings(result, indent=indent), click.style(f"{indent}{note}", dim=True)]


def _signal_summary(rows: list[Mapping[str, Any]], *, indent: str) -> list[str] | None:
    result = []
    for row in rows:
        value = row.get("after", row.get("value"))
        if not isinstance(value, Mapping):
            return None
        numbers = [float(item) for item in value.values() if isinstance(item, (int, float))]
        result.append({"owner": str(row.get("strategy") or route_label(row)), "count": len(value),
                       "positive": sum(item > 0 for item in numbers), "negative": sum(item < 0 for item in numbers),
                       "zero": sum(item == 0 for item in numbers), "min": min(numbers, default=None), "max": max(numbers, default=None)})
    return [*table_from_mappings(result, indent=indent), click.style(f"{indent}逐品种信号请使用 job step-field 查看。", dim=True)]


def _trade_intents(rows: list[Mapping[str, Any]], *, indent: str) -> list[str] | None:
    result = []
    for row in rows:
        value = row.get("after", row.get("value"))
        if not isinstance(value, Mapping) or "weights" not in value:
            return None
        weights = value.get("weights")
        result.append({
            "owner": str(row.get("strategy") or route_label(row)),
            "type": value.get("type"), "reason": value.get("reason"),
            "weight_count": len(weights) if isinstance(weights, Mapping) else 0,
        })
    return [
        *table_from_mappings(result, indent=indent),
        click.style(f"{indent}intent weights 由 target_weights 表表示；job step-field 可查看完整 intent。", dim=True),
    ]
