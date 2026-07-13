"""Generic value-to-text helpers for audit output."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from tools.cli.modules.backtest.audit_formatters import table_render
from tools.data.types.data_money import _format_data_money


TableLines = Callable[..., list[str]]
ScalarCell = Callable[[Any], str]
CashSummary = Callable[[Any], str]
HistoricalSummary = Callable[[Any], dict[str, Any] | None]
HistoricalSummaryPredicate = Callable[[dict[str, Any]], bool]
HistoricalText = Callable[[dict[str, Any]], str]


def scalar_sequence_text(
    value: list[Any] | tuple[Any, ...],
    *,
    width: int = 72,
) -> str:
    items = [str(item) for item in value]
    if not items:
        return "[]"
    lines: list[str] = []
    current = "["
    for index, item in enumerate(items):
        token = item + ("," if index < len(items) - 1 else "")
        separator = "" if current.endswith("[") else " "
        candidate = f"{current}{separator}{token}"
        if table_render.display_width_text(candidate) <= width:
            current = candidate
            continue
        if current != "[":
            lines.append(current)
            current = f"  {token}"
        else:
            lines.append(f"[{token}")
            current = "  "
    closing_candidate = f"{current}]"
    if table_render.display_width_text(closing_candidate) <= width:
        lines.append(closing_candidate)
    else:
        if current.strip():
            lines.append(current)
        lines.append("]")
    return "\n".join(lines)


def scalar_cell(value: Any, *, cash_summary: CashSummary) -> str:
    if value is None:
        return "null"
    if table_render.is_data_money_dict(value):
        return cash_summary(value)
    if isinstance(value, float):
        return f"{value:.12g}"
    return str(value)


def cash_summary(value: Any, *, audit_text: Callable[[Any], str]) -> str:
    if value is None:
        return "null"
    if isinstance(value, dict):
        amount = value.get("amount")
        amount_value: Any = amount
        if isinstance(amount, dict):
            amount_value = amount.get("repr", amount.get("value"))
        currency = str(value.get("currency") or "")
        scale = value.get("scale")
        use_minor = bool(value.get("use_minor_units"))
        if currency and scale not in (None, ""):
            try:
                return _format_data_money(amount_value, currency, use_minor, int(scale))
            except (TypeError, ValueError):
                pass
        return f"DataMoney({' '.join(str(part) for part in (amount_value, currency) if part not in (None, ''))})"
    return audit_text(value).replace("\n", " ")


def mapping_table_text(
    value: Any,
    *,
    table_lines: TableLines,
    scalar_cell: ScalarCell,
    historical_summary: HistoricalSummary,
    is_historical_summary: HistoricalSummaryPredicate,
    historical_text: HistoricalText,
) -> str | None:
    if not isinstance(value, dict) or not value:
        return None
    if any(str(key) == "type" for key in value):
        return None
    if all(not isinstance(item, (dict, list, tuple)) for item in value.values()):
        rows = [(str(key), scalar_cell(item)) for key, item in value.items()]
        return "\n".join(table_lines(("key", "value"), rows))
    if all(isinstance(item, dict) for item in value.values()):
        summary = historical_summary(value)
        if summary is not None and is_historical_summary(summary):
            return historical_text(summary)
        child_keys: list[str] = []
        for item in value.values():
            if not isinstance(item, dict):
                return None
            for child_key, child_value in item.items():
                if isinstance(child_value, (dict, list, tuple)):
                    return None
                child_key_text = str(child_key)
                if child_key_text not in child_keys:
                    child_keys.append(child_key_text)
        if not child_keys:
            return None
        rows = [
            tuple([str(key), *[scalar_cell(item.get(child_key)) for child_key in child_keys]])
            for key, item in value.items()
            if isinstance(item, dict)
        ]
        return "\n".join(table_lines(("key", *child_keys), rows))
    return None


def sequence_mapping_table_text(
    value: Any,
    *,
    table_lines: TableLines,
    scalar_cell: ScalarCell,
) -> str | None:
    if not isinstance(value, (list, tuple)) or not value:
        return None
    if len(value) > 6 or not all(isinstance(item, dict) for item in value):
        return None
    child_keys: list[str] = []
    for item in value:
        for child_key, child_value in item.items():
            if isinstance(child_value, (dict, list, tuple)):
                return None
            child_key_text = str(child_key)
            if child_key_text not in child_keys:
                child_keys.append(child_key_text)
    if not child_keys:
        return None
    rows = [
        tuple(scalar_cell(item.get(child_key)) for child_key in child_keys)
        for item in value
    ]
    return "\n".join(table_lines(tuple(child_keys), rows, allow_transpose=False))


def contract_metadata_text(value: dict[str, Any], *, table_lines: TableLines) -> str:
    rows = value.get("rows")
    if not isinstance(rows, list):
        return "contract_metadata: (no rows)"
    table_rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        table_rows.append((
            row.get("product") or "",
            row.get("contract") or "",
            row.get("start") or "",
            row.get("end") or "",
        ))
    if not table_rows:
        return "contract_metadata: (empty)"
    return "\n".join(table_lines(
        ("原产品", "新合约", "起始时间", "终止时间"),
        table_rows,
    ))
