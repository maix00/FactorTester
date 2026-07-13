"""Order-delta audit table helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from tools.cli.modules.backtest.audit_formatters import scope_tables


Normalize = Callable[[Any], Any]
ScalarCell = Callable[[Any], str]
ChangeCell = Callable[[Any, Any], str]
DisplayFieldValue = Callable[[str, Any], Any]


DeltaTable = tuple[tuple[str, ...], list[tuple[str, str, str, str, str]]]

ORDER_DELTA_FIELD_NAMES = {"raw_deltas", "sized_deltas", "deltas"}


def is_delta_field(field_name: str) -> bool:
    return field_name.rsplit(".", 1)[-1] in ORDER_DELTA_FIELD_NAMES


def delta_mapping(value: Any, *, normalize: Normalize) -> dict[str, Any] | None:
    normalized = normalize(value)
    if normalized in (None, ""):
        return {}
    if not isinstance(normalized, Mapping):
        return None
    result: dict[str, Any] = {}
    for product, quantity in normalized.items():
        if isinstance(quantity, (dict, list, tuple)):
            return None
        result[str(product)] = quantity
    return result


def delta_routes(
    entry: Mapping[str, Any],
    *,
    strategy_ledger_routes: Mapping[str, tuple[tuple[str, str], ...]],
) -> list[tuple[str, str, str]]:
    strategy = entry.get("strategy")
    if strategy not in (None, ""):
        strategy_text = scope_tables.scope_route(entry, ("strategy",))[0]
        mapped_routes = strategy_ledger_routes.get(strategy_text)
        if mapped_routes:
            return [(ledger, cash_pool, strategy_text) for ledger, cash_pool in mapped_routes]
        return [("?", "?", strategy_text)]
    strategies = entry.get("strategies")
    if isinstance(strategies, list) and strategies:
        strategy_values = [str(item) for item in strategies if item not in (None, "")]
    else:
        strategy_values = []
    ledger = entry.get("ledger")
    cash_pool = entry.get("cash_pool")
    if ledger not in (None, "") or cash_pool not in (None, ""):
        ledger_text, cash_pool_text = scope_tables.scope_route(entry, ("ledger", "cash_pool"))
        return [(ledger_text, cash_pool_text, ", ".join(strategy_values) or "无")]
    if strategy_values:
        routes: list[tuple[str, str, str]] = []
        for strategy_text in strategy_values:
            mapped_routes = strategy_ledger_routes.get(strategy_text)
            if mapped_routes:
                routes.extend((ledger_id, cash_pool, strategy_text) for ledger_id, cash_pool in mapped_routes)
            else:
                routes.append(("?", "?", strategy_text))
        return routes
    return [("[共享]", "[共享]", "无")]


def delta_value_rows(
    routes: list[tuple[str, str, str]],
    mapping: dict[str, Any],
    *,
    scalar_cell: ScalarCell,
) -> list[tuple[str, str, str, str, str]]:
    rows: list[tuple[str, str, str, str, str]] = []
    zero_count = 0
    for product, value in sorted(mapping.items()):
        if is_zero_value(value):
            zero_count += 1
            continue
        for ledger, cash_pool, strategies in routes:
            rows.append((ledger, cash_pool, strategies, product, scalar_cell(value)))
    if zero_count:
        for ledger, cash_pool, strategies in routes:
            rows.append((ledger, cash_pool, strategies, f"其余 {zero_count} 个产品", "0"))
    if not rows:
        for ledger, cash_pool, strategies in routes:
            rows.append((ledger, cash_pool, strategies, "全部产品", "0"))
    return rows


def delta_change_rows(
    routes: list[tuple[str, str, str]],
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    scalar_cell: ScalarCell,
    change_cell: ChangeCell,
) -> list[tuple[str, str, str, str, str]]:
    rows: list[tuple[str, str, str, str, str]] = []
    zero_change_count = 0
    missing = object()
    for product in sorted(set(before) | set(after)):
        before_value = before.get(product, missing)
        after_value = after.get(product, missing)
        if before_value == after_value:
            continue
        before_text = "null" if before_value is missing else scalar_cell(before_value)
        after_text = "null" if after_value is missing else scalar_cell(after_value)
        if is_zero_text(after_text) and before_text in {"null", "0"}:
            zero_change_count += 1
            continue
        for ledger, cash_pool, strategies in routes:
            rows.append((ledger, cash_pool, strategies, product, change_cell(before_text, after_text)))
    if zero_change_count:
        for ledger, cash_pool, strategies in routes:
            rows.append((ledger, cash_pool, strategies, f"其余 {zero_change_count} 个产品", change_cell("null", "0")))
    return rows


def delta_value_table(
    field_name: str,
    values: list[dict[str, Any]],
    *,
    display_field_value: DisplayFieldValue,
    normalize: Normalize,
    strategy_ledger_routes: Mapping[str, tuple[tuple[str, str], ...]],
    scalar_cell: ScalarCell,
) -> DeltaTable | None:
    short_name = field_name.rsplit(".", 1)[-1]
    if not is_delta_field(field_name) or not values:
        return None
    rows: list[tuple[str, str, str, str, str]] = []
    for entry in values:
        mapping = delta_mapping(display_field_value(field_name, entry.get("value")), normalize=normalize)
        if mapping is None:
            return None
        rows.extend(delta_value_rows(
            delta_routes(entry, strategy_ledger_routes=strategy_ledger_routes),
            mapping,
            scalar_cell=scalar_cell,
        ))
    return ("ledger", "cash pool", "strategies", "product", short_name), rows


def delta_change_table(
    field_name: str,
    changes: list[dict[str, Any]],
    *,
    display_field_value: DisplayFieldValue,
    normalize: Normalize,
    strategy_ledger_routes: Mapping[str, tuple[tuple[str, str], ...]],
    scalar_cell: ScalarCell,
    change_cell: ChangeCell,
) -> DeltaTable | None:
    short_name = field_name.rsplit(".", 1)[-1]
    if not is_delta_field(field_name) or not changes:
        return None
    rows: list[tuple[str, str, str, str, str]] = []
    for change in changes:
        before_mapping = delta_mapping(display_field_value(field_name, change.get("before")), normalize=normalize)
        after_mapping = delta_mapping(display_field_value(field_name, change.get("after")), normalize=normalize)
        if before_mapping is None or after_mapping is None:
            return None
        rows.extend(delta_change_rows(
            delta_routes(change, strategy_ledger_routes=strategy_ledger_routes),
            before_mapping,
            after_mapping,
            scalar_cell=scalar_cell,
            change_cell=change_cell,
        ))
    return ("ledger", "cash pool", "strategies", "product", short_name), rows


def is_zero_value(value: Any) -> bool:
    try:
        return float(value) == 0.0
    except (TypeError, ValueError):
        return str(value).strip() in {"0", "0.0"}


def is_zero_text(value: str) -> bool:
    try:
        return float(value) == 0.0
    except (TypeError, ValueError):
        return value.strip() in {"0", "0.0"}
