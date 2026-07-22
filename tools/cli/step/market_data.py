"""Semantic tables for market-data planning and field-state values."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import click

from .values import scalar, table_from_mappings


def render_input(field: str, value: Any, *, indent: str) -> list[str] | None:
    if field.endswith((".raw_prices", ".settlement_price", ".volume")):
        return _frame_summary(value, indent=indent)
    if field.endswith(".trading_day_resolver"):
        return _resolver_summary(value, indent=indent)
    if field.endswith(".price_tables"):
        return _price_tables(value, indent=indent)
    return None


def render_change(field: str, value: Any, *, indent: str) -> list[str] | None:
    if field.endswith(".market_data_load_plan"):
        return _load_plan(value, indent=indent)
    if field.endswith(".excluded_out_of_range_products"):
        return _typed_rows(value, "MarketDataExcludedProducts", indent=indent)
    if field.endswith(".price_tables"):
        return _price_tables(value, indent=indent)
    if field.endswith(".field_state_baseline"):
        return _field_state(value, indent=indent)
    if field.endswith(".current_historical_fields"):
        return _field_state(value, indent=indent)
    if field.endswith((".current_prices", ".volume")):
        return _scalar_map(value, field.rsplit(".", 1)[-1], indent=indent)
    if field.endswith(".current_market_snapshot"):
        return _market_snapshot(value, indent=indent)
    if field.endswith(".current_tradable_status"):
        return _tradable_status(value, indent=indent)
    if field.endswith(".current_order_constraints"):
        return _order_constraints(value, indent=indent)
    return None


def _load_plan(value: Any, *, indent: str) -> list[str] | None:
    if not isinstance(value, Mapping) or value.get("type") != "MarketDataLoadPlan":
        return None
    items = value.get("items")
    if not isinstance(items, Mapping):
        return None
    rows = [
        {"instrument": instrument, "source": item.get("data_source"), "frequency": item.get("frequency")}
        for instrument, item in items.items() if isinstance(item, Mapping)
    ]
    return table_from_mappings(rows, indent=indent)


def _typed_rows(value: Any, expected_type: str, *, indent: str) -> list[str] | None:
    if not isinstance(value, Mapping) or value.get("type") != expected_type:
        return None
    rows = value.get("rows")
    return table_from_mappings(rows, indent=indent) if isinstance(rows, list) else None


def _price_tables(value: Any, *, indent: str) -> list[str] | None:
    if not isinstance(value, Mapping) or value.get("type") != "PriceTablesSummary":
        return None
    rows = []
    for item in value.get("rows") or []:
        if not isinstance(item, Mapping):
            continue
        index = item.get("index") if isinstance(item.get("index"), Mapping) else {}
        columns = item.get("columns")
        if isinstance(columns, Mapping):
            column_count = columns.get("count")
            sampled = columns.get("sampled") or []
        else:
            column_count = len(columns or [])
            sampled = columns or []
        rows.append({
            "basis": item.get("basis"), "shape": item.get("shape"),
            "start": index.get("start"), "end": index.get("end"),
            "columns": column_count, "sampled_columns": sampled[:5],
        })
    return [
        *table_from_mappings(rows, indent=indent),
        click.style(f"{indent}样本矩阵未重复展开；可用 job step-field 查看该字段保留的 head/tail。", dim=True),
    ]


def _frame_summary(value: Any, *, indent: str) -> list[str] | None:
    if not isinstance(value, Mapping) or value.get("type") != "DataFrame":
        return None
    sample = value.get("sample") if isinstance(value.get("sample"), Mapping) else {}
    head = sample.get("head") if isinstance(sample.get("head"), Mapping) else {}
    tail = sample.get("tail") if isinstance(sample.get("tail"), Mapping) else {}
    columns = head.get("columns") or []
    indices = [*(head.get("index") or []), *(tail.get("index") or [])]
    return table_from_mappings([{
        "shape": value.get("shape"), "start": indices[0] if indices else None,
        "end": indices[-1] if indices else None, "sampled_columns": len(columns),
    }], indent=indent)


def _resolver_summary(value: Any, *, indent: str) -> list[str] | None:
    if not isinstance(value, Mapping) or value.get("type") != "TimestampTradingDayResolver":
        return None
    timestamps = value.get("timestamp_index") if isinstance(value.get("timestamp_index"), Mapping) else {}
    days = value.get("trading_days") if isinstance(value.get("trading_days"), Mapping) else {}
    return table_from_mappings([{
        "timestamps": value.get("mapping_count"), "start": timestamps.get("start"),
        "end": timestamps.get("end"), "trading_days": days.get("count"),
        "day_start": days.get("start"), "day_end": days.get("end"),
    }], indent=indent)


def _field_state(value: Any, *, indent: str) -> list[str] | None:
    if not isinstance(value, Mapping) or not value or not all(isinstance(item, Mapping) for item in value.values()):
        return None
    groups = (
        ("会计语义", ("CostBasisMethod", "MoneyCalculationPolicy")),
        ("合约与保证金", ("VolumeMultiple", "LongMarginRatioByMoney", "ShortMarginRatioByMoney", "LongMarginRatioByVolume", "ShortMarginRatioByVolume")),
        ("按金额费率", ("OpenRatioByMoney", "CloseRatioByMoney", "CloseTodayRatioByMoney")),
        ("按手数费率", ("OpenRatioByVolume", "CloseRatioByVolume", "CloseTodayRatioByVolume")),
    )
    lines: list[str] = []
    for title, fields in groups:
        if not any(field in item for item in value.values() for field in fields):
            continue
        lines.append(f"{indent}{title}:")
        rows = [
            {"product": product, **{field: scalar(item.get(field)) for field in fields}}
            for product, item in value.items()
        ]
        lines.extend(table_from_mappings(rows, indent=indent + "  "))
    return lines


def _scalar_map(value: Any, label: str, *, indent: str) -> list[str] | None:
    if not isinstance(value, Mapping) or not value or not all(not isinstance(item, Mapping) for item in value.values()):
        return None
    return table_from_mappings(
        ({"instrument": instrument, label: scalar(item)} for instrument, item in value.items()),
        indent=indent,
    )


def _market_snapshot(value: Any, *, indent: str) -> list[str] | None:
    if not isinstance(value, Mapping) or not value or not all(isinstance(item, Mapping) for item in value.values()):
        return None
    instruments = list(dict.fromkeys(
        instrument for basis in value.values() for instrument in basis
    ))
    rows = [
        {"instrument": instrument, **{basis: scalar(values.get(instrument)) for basis, values in value.items()}}
        for instrument in instruments
    ]
    return table_from_mappings(rows, indent=indent)


def _tradable_status(value: Any, *, indent: str) -> list[str] | None:
    if not isinstance(value, Mapping) or not all(isinstance(item, bool) for item in value.values()):
        return None
    blocked = [instrument for instrument, tradable in value.items() if not tradable]
    lines = [f"{indent}tradable={len(value) - len(blocked)}, blocked={len(blocked)}"]
    if blocked:
        lines.extend(table_from_mappings(({"instrument": item, "tradable": False} for item in blocked), indent=indent))
    return lines


def _order_constraints(value: Any, *, indent: str) -> list[str] | None:
    if not isinstance(value, Mapping) or not all(isinstance(item, Mapping) for item in value.values()):
        return None
    exceptions = [
        {"instrument": instrument, **constraint}
        for instrument, constraint in value.items()
        if not constraint.get("tradable") or not constraint.get("can_buy")
        or not constraint.get("can_sell") or constraint.get("reason")
        or constraint.get("limit_up_price") or constraint.get("limit_down_price")
    ]
    normal = len(value) - len(exceptions)
    return [
        f"{indent}normal={normal}, constrained={len(exceptions)}",
        *table_from_mappings(exceptions, indent=indent),
        click.style(f"{indent}正常约束未逐品种重复；job step-field 可查看完整约束映射。", dim=True),
    ]
