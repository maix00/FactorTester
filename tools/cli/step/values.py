"""Scalar, structured-value, and generic table rendering for step events."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

import click

from tools.cli.table import render_table


SCOPE_COLUMNS = ("scope", "strategy", "ledger", "cash_pool", "strategies")


def render_value(value: Any, *, indent: str, highlight: bool = False) -> list[str]:
    table = typed_table(value, indent=indent)
    if table is not None:
        return [_highlight_after_indent(line) if highlight else line for line in table]
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    lines = [indent + line for line in text.splitlines()]
    return [_highlight_after_indent(line) if highlight else line for line in lines]


def typed_table(value: Any, *, indent: str) -> list[str] | None:
    if not isinstance(value, Mapping):
        return None
    value_type = value.get("type")
    if value_type in {"ContractMetadataTable", "PriceTablesSummary"} and isinstance(value.get("rows"), list):
        return [*table_from_mappings(value["rows"], indent=indent), *truncation_note(value, indent)]
    if value_type == "DataFrame" and isinstance(value.get("rows"), list):
        return table_from_mappings(_frame_rows(value), indent=indent)
    if value_type in {"DataFrame", "Series", "list"} and isinstance(value.get("sample"), Mapping):
        lines = [f"{indent}{value_type} {shape_text(value)}"]
        for side in ("head", "tail"):
            sample = value["sample"].get(side)
            if sample is None:
                continue
            lines.append(f"{indent}{side}:")
            if isinstance(sample, Mapping) and isinstance(sample.get("rows"), list):
                lines.extend(table_from_mappings(_frame_rows(sample), indent=indent + "  "))
            else:
                lines.extend(render_value(sample, indent=indent + "  "))
        return [*lines, *truncation_note(value, indent)]
    return None


def table_from_mappings(rows: Iterable[Mapping[str, Any]], *, indent: str) -> list[str]:
    materialized = [dict(row) for row in rows]
    if not materialized:
        return []
    headers: list[str] = []
    for row in materialized:
        for key in row:
            if str(key) not in headers:
                headers.append(str(key))
    values = [tuple(scalar(row.get(header)) for header in headers) for row in materialized]
    return render_table(tuple(headers), values, indent=indent)


def scope(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value.get(key) for key in SCOPE_COLUMNS if value.get(key) not in (None, "", [])}


def route_label(value: Mapping[str, Any]) -> str:
    return ", ".join(f"{key}={item}" for key, item in scope(value).items()) or "shared"


def is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool)) or is_money(value)


def scalar(value: Any) -> str:
    if value is None:
        return "null"
    if is_money(value):
        amount = value.get("amount")
        if isinstance(amount, Mapping):
            amount = amount.get("repr", amount.get("value"))
        unit = "minor" if value.get("use_minor_units") else "major"
        scale = value.get("scale")
        suffix = f", scale={scale}" if scale not in (None, "") else ""
        return f"{amount} {value.get('currency')} ({unit}{suffix})"
    if isinstance(value, (list, tuple)) and all(is_scalar(item) for item in value):
        return ", ".join(scalar(item) for item in value)
    if isinstance(value, Mapping):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def highlighted(value: Any) -> str:
    return _highlight(scalar(value))


def _frame_rows(value: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {"index": index} | dict(zip(value.get("columns") or [], row))
        for index, row in zip(value.get("index") or [], value.get("rows") or [])
    ]


def truncation_note(value: Mapping[str, Any], indent: str) -> list[str]:
    if not value.get("truncated"):
        return []
    message = "… 后端值已采样；使用 job step-field 查看该事件中保留的完整序列化内容"
    return [click.style(f"{indent}{message}", dim=True)]


def shape_text(value: Mapping[str, Any]) -> str:
    if value.get("shape") is not None:
        return f"shape={value['shape']}"
    if value.get("length") is not None:
        return f"length={value['length']}"
    return ""


def is_money(value: Any) -> bool:
    return isinstance(value, Mapping) and {"amount", "currency", "use_minor_units"} <= set(value)


def _highlight(text: str) -> str:
    return click.style(text, fg="bright_yellow", bold=True)


def _highlight_after_indent(text: str) -> str:
    content = text.lstrip(" ")
    return text[: len(text) - len(content)] + _highlight(content)
