"""Trade-intent and target-weight audit formatting helpers."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any


TableLines = Callable[..., list[str]]
ScalarCell = Callable[[Any], str]
ChangeCell = Callable[[Any, Any], str]
DisplayKey = Callable[[Any], str]
Normalize = Callable[[Any], Any]


def trade_intent_text(value: Mapping[str, Any], *, table_lines: TableLines, scalar_cell: ScalarCell) -> str:
    if value.get("type") == "TargetWeightIntent":
        rows = weight_rows(value.get("weights"), scalar_cell=scalar_cell)
        lines = [f"reason = {value.get('reason') or ''}"]
        if rows:
            lines.extend(table_lines(("product", "target_weight"), rows))
        return "\n".join(lines)
    if value.get("type") == "OrderDeltaIntent":
        rows = weight_rows(value.get("deltas"), scalar_cell=scalar_cell)
        lines = [f"reason = {value.get('reason') or ''}"]
        if rows:
            lines.extend(table_lines(("product", "delta"), rows))
        return "\n".join(lines)
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)


def weight_rows(value: Any, *, scalar_cell: ScalarCell) -> list[tuple[str, str]]:
    if not isinstance(value, Mapping):
        return []
    return [(str(product), scalar_cell(weight)) for product, weight in value.items()]


def weight_change_field(field_name: str) -> str | None:
    short_name = field_name.rsplit(".", 1)[-1]
    if short_name == "target_weights":
        return "target_weight"
    if short_name == "trade_intent":
        return "target_weight"
    return None


def weight_mapping(value: Any, *, normalize: Normalize) -> dict[str, Any]:
    normalized = normalize(value)
    if not isinstance(normalized, Mapping):
        return {}
    if normalized.get("type") == "TargetWeightIntent":
        weights = normalized.get("weights")
        return dict(weights) if isinstance(weights, Mapping) else {}
    if normalized.get("type") == "OrderDeltaIntent":
        deltas = normalized.get("deltas")
        return dict(deltas) if isinstance(deltas, Mapping) else {}
    if "weights" in normalized and isinstance(normalized.get("weights"), Mapping):
        return dict(normalized["weights"])
    if "deltas" in normalized and isinstance(normalized.get("deltas"), Mapping):
        return dict(normalized["deltas"])
    if "type" not in normalized and all(not isinstance(item, (dict, list, tuple)) for item in normalized.values()):
        return dict(normalized)
    return {}


def intent_reason(value: Any, *, normalize: Normalize) -> str:
    normalized = normalize(value)
    if isinstance(normalized, Mapping):
        reason = normalized.get("reason")
        return "" if reason in (None, "") else str(reason)
    return ""


def compact_identical_weight_rows(
    rows: Sequence[tuple[str, dict[str, Any], str]],
    *,
    display_key: DisplayKey,
) -> list[tuple[str, dict[str, Any], str]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for strategy, weights, reason in rows:
        key = (display_key(weights), reason)
        bucket = grouped.setdefault(key, {"strategies": [], "weights": weights, "reason": reason})
        bucket["strategies"].append(strategy)
    compacted: list[tuple[str, dict[str, Any], str]] = []
    for bucket in grouped.values():
        compacted.append((
            ", ".join(str(item) for item in bucket["strategies"]),
            bucket["weights"],
            bucket["reason"],
        ))
    return compacted


def weight_table_lines(
    rows: list[tuple[str, dict[str, Any], str]],
    *,
    value_label: str,
    table_lines: TableLines,
    scalar_cell: ScalarCell,
    display_key: DisplayKey,
    include_reason: bool = False,
    indent: str = "",
) -> list[str]:
    if not rows:
        return [f"{indent}（无值）"]
    compacted = compact_identical_weight_rows(rows, display_key=display_key)
    products: list[str] = []
    for _, weights, _ in compacted:
        for product in weights:
            product_text = str(product)
            if product_text not in products:
                products.append(product_text)
    products.sort()
    if not products:
        headers = ("strategy", "reason") if include_reason else ("strategy", value_label)
        empty_rows = [
            (strategy, reason) if include_reason else (strategy, "null")
            for strategy, _, reason in compacted
        ]
        return table_lines(headers, empty_rows, indent=indent)
    headers = ["strategy"]
    if include_reason:
        headers.append("reason")
    headers.extend(products)
    table_rows: list[tuple[Any, ...]] = []
    for strategy, weights, reason in compacted:
        row: list[Any] = [strategy]
        if include_reason:
            row.append(reason)
        row.extend(scalar_cell(weights.get(product, "")) for product in products)
        table_rows.append(tuple(row))
    return table_lines(headers, table_rows, indent=indent)


def weight_change_table_lines(
    rows: list[tuple[str, dict[str, Any], dict[str, Any], str, str]],
    *,
    value_label: str,
    table_lines: TableLines,
    scalar_cell: ScalarCell,
    change_cell: ChangeCell,
    display_key: DisplayKey,
    include_reason: bool = False,
    indent: str = "",
) -> list[str]:
    if not rows:
        return [f"{indent}（无变化）"]
    headers = ["strategy", "product", value_label]
    if include_reason:
        headers.append("reason")
    table_rows: list[tuple[Any, ...]] = []
    for strategy, before_weights, after_weights, before_reason, after_reason in compact_weight_change_rows(rows, display_key=display_key):
        reason_cell = (
            change_cell(before_reason or "null", after_reason or "null")
            if before_reason != after_reason else before_reason
        )
        products = sorted(str(product) for product in (set(before_weights) | set(after_weights)))
        emitted = False
        for product in products:
            before_value = scalar_cell(before_weights.get(product))
            after_value = scalar_cell(after_weights.get(product))
            if before_value == after_value and not reason_cell:
                continue
            row: list[Any] = [strategy, product, "" if before_value == after_value else change_cell(before_value, after_value)]
            if include_reason:
                row.append(reason_cell)
            table_rows.append(tuple(row))
            emitted = True
        if not emitted and reason_cell:
            row = [strategy, "（无产品权重变化）", ""]
            if include_reason:
                row.append(reason_cell)
            table_rows.append(tuple(row))
    if not table_rows:
        return [f"{indent}（无变化）"]
    return table_lines(headers, table_rows, indent=indent)


def compact_weight_change_rows(
    rows: Sequence[tuple[str, dict[str, Any], dict[str, Any], str, str]],
    *,
    display_key: DisplayKey,
) -> list[tuple[str, dict[str, Any], dict[str, Any], str, str]]:
    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for strategy, before_weights, after_weights, before_reason, after_reason in rows:
        key = (
            display_key(before_weights),
            display_key(after_weights),
            before_reason,
            after_reason,
        )
        bucket = grouped.setdefault(
            key,
            {
                "strategies": [],
                "before": before_weights,
                "after": after_weights,
                "before_reason": before_reason,
                "after_reason": after_reason,
            },
        )
        bucket["strategies"].append(strategy)
    return [
        (
            ", ".join(str(item) for item in bucket["strategies"]),
            bucket["before"],
            bucket["after"],
            bucket["before_reason"],
            bucket["after_reason"],
        )
        for bucket in grouped.values()
    ]


def trade_intent_summary(value: Any, *, normalize: Normalize) -> str | None:
    normalized = normalize(value)
    if not isinstance(normalized, Mapping):
        return None
    intent_type = str(normalized.get("type") or "").strip()
    if intent_type not in {"TargetWeightIntent", "OrderDeltaIntent"}:
        return None
    reason = str(normalized.get("reason") or "").strip()
    payload = normalized.get("weights") if intent_type == "TargetWeightIntent" else normalized.get("deltas")
    count = len(payload) if isinstance(payload, Mapping) else 0
    suffix = "weights" if intent_type == "TargetWeightIntent" else "deltas"
    if reason:
        return f"{intent_type}(reason={reason}; {count} {suffix})"
    return f"{intent_type}({count} {suffix})"
