"""Field-value normalization and compact display helpers for audit output."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any
import ast
import json


Summary = Callable[[Any], Any | None]
CashSummary = Callable[[Any], str]
ScalarSequenceText = Callable[[list[Any] | tuple[Any, ...]], str]
ProductListCell = Callable[[list[str]], str]


def parse_literal(value: str) -> Any | None:
    text = value.strip()
    if len(text) < 2 or text[0] not in "[{":
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        pass
    try:
        parsed = ast.literal_eval(text)
    except (SyntaxError, ValueError, TypeError, MemoryError, RecursionError):
        return None
    if isinstance(parsed, (dict, list, tuple)):
        return parsed
    return None


def compact_aliases(value: Any) -> Any:
    if isinstance(value, dict):
        compacted = {
            str(key): compact_aliases(item)
            for key, item in value.items()
        }
        if looks_like_product_path_selection(compacted):
            return compact_product_path_selection(compacted)
        return compacted
    if isinstance(value, list):
        return [compact_aliases(item) for item in value]
    if isinstance(value, tuple):
        return [compact_aliases(item) for item in value]
    return value


def looks_like_product_path_selection(value: Mapping[str, Any]) -> bool:
    return bool(
        "product_path_selection_id" in value
        or ("id" in value and ("selected_paths" in value or "paths" in value))
        or ("selected_paths" in value and "paths" in value)
        or ("product_group_template_id" in value and "path_id" in value)
    )


def compact_product_path_selection(value: Mapping[str, Any]) -> dict[str, Any]:
    compacted: dict[str, Any] = {}
    selection_id = value.get("product_path_selection_id") or value.get("selection_id") or value.get("id")
    if selection_id not in (None, ""):
        compacted["product_path_selection_id"] = selection_id
    label = value.get("label") or value.get("product_group")
    if label not in (None, ""):
        compacted["label"] = label
    product_group = value.get("product_group")
    if product_group not in (None, "", label):
        compacted["product_group"] = product_group
    template_id = value.get("product_group_template_id") or value.get("path_id")
    if template_id not in (None, ""):
        compacted["product_group_template_id"] = template_id
    paths = value.get("paths") if "paths" in value else value.get("selected_paths")
    if paths not in (None, ""):
        compacted["paths"] = paths
    source_type = value.get("source_type")
    if source_type not in (None, ""):
        compacted["source_type"] = source_type
    source_key = value.get("source_key")
    if source_key not in (None, "", selection_id, template_id):
        compacted["source_key"] = source_key
    return compacted


def display_field_value(
    qualified_name: str,
    value: Any,
    *,
    trade_intent_summary: Summary,
    positions_summary: Summary,
    run_window_summary: Summary,
    historical_field_state_summary: Summary,
    cash_summary: CashSummary,
    scalar_sequence_text: ScalarSequenceText,
    field_display_offsets: Mapping[str, int],
) -> Any:
    if qualified_name.rsplit(".", 1)[-1] == "trade_intent":
        summary = trade_intent_summary(value)
        if summary is not None:
            return summary
    if qualified_name == "LedgerModule.positions" or qualified_name.rsplit(".", 1)[-1] == "positions":
        summary = positions_summary(value)
        if summary is not None:
            return summary
    if qualified_name in {"RunWindowModule.run_window_envelope", "RunWindowModule.strategy_windows"}:
        summary = run_window_summary(value)
        if summary is not None:
            return summary
    if qualified_name == "MarketDataModule.field_state_baseline":
        summary = historical_field_state_summary(value)
        if summary is not None:
            return summary
    if qualified_name == "MarketDataModule.required_data_source" and value in ((), []):
        return "auto（自动选择）"
    if qualified_name.rsplit(".", 1)[-1] == "cash":
        return cash_summary(value)
    if isinstance(value, (list, tuple)) and all(not isinstance(item, (dict, list, tuple)) for item in value):
        return scalar_sequence_text(value)
    offset = field_display_offsets.get(qualified_name, field_display_offsets.get(qualified_name.rsplit(".", 1)[-1], 0))
    if offset and isinstance(value, (int, float)) and not isinstance(value, bool):
        return value + offset
    return value


def display_key(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def normalized_value(value: Any) -> Any:
    if isinstance(value, str):
        parsed = parse_literal(value)
        if parsed is not None:
            return compact_aliases(parsed)
    return compact_aliases(value)


def repeated_owner_groups(
    value: Any,
    *,
    product_list_cell: ProductListCell,
) -> list[tuple[str, Any]]:
    normalized = normalized_value(value)
    if not isinstance(normalized, dict) or len(normalized) <= 1:
        return []
    items = list(normalized.items())
    if not all(isinstance(item_value, (dict, list)) for _, item_value in items):
        return []
    groups: dict[str, dict[str, Any]] = {}
    for item_key, item_value in items:
        group_key = display_key(item_value)
        bucket = groups.setdefault(group_key, {"keys": [], "value": item_value})
        bucket["keys"].append(str(item_key))
    if len(groups) >= len(items):
        return []
    return [
        (f"{group_key_label(bucket['keys'])} {group_keys_text(sorted(bucket['keys']), product_list_cell=product_list_cell)}", bucket["value"])
        for bucket in groups.values()
    ]


def group_keys_text(keys: list[str], *, product_list_cell: ProductListCell) -> str:
    if not keys:
        return "无"
    return product_list_cell(keys)


def group_key_label(keys: list[str]) -> str:
    price_bases = {
        "open", "high", "low", "close", "vwap", "settlement", "pre_settlement",
        "upper_limit", "lower_limit", "volume",
    }
    if keys and all(key in price_bases for key in keys):
        return "价格字段"
    if keys and all("." in key or "|" in key for key in keys):
        return "产品"
    return "策略"


def inline_summary(value: Any, *, audit_text: Callable[[Any], str], display_width: Callable[[object], int]) -> str:
    text = audit_text(value).splitlines()
    if not text:
        return ""
    first = text[0].strip()
    if len(text) == 1 and display_width(first) <= 80:
        return first
    return f"{first} ... ({len(text)} 行)"
