"""Order audit formatting helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any


TableLines = Callable[..., list[str]]
ScalarCell = Callable[[Any], str]
ChangeCell = Callable[[Any, Any], str]
HighlightCell = Callable[[str], str]
StrategyLabel = Callable[[Any], str]
SelectSamplePart = Callable[[dict[str, Any], Any], Any]


ORDER_BASE_COLUMNS = [
    "order_id", "strategy", "timestamp", "instrument", "intent_quantity", "quantity",
    "status", "reject_reason",
]
ORDER_PREFERRED_FIELD_COLUMNS = [
    "price_timestamp",
    "execution_price_basis",
    "effective_price",
    "fee_open_quantity",
    "fee_close_quantity",
    "fee_close_today_quantity",
    "fee_close_yesterday_quantity",
    "fee_close_today",
    "fee_cost",
    "margin_required",
    "available_cash",
    "cash_required",
    "max_quantity",
]


def order_table_text(
    value: Any,
    *,
    table_lines: TableLines,
    scalar_cell: ScalarCell,
    strategy_label: StrategyLabel,
    select_sample_part: SelectSamplePart,
    sample_note_lines: Callable[[dict[str, Any], str], list[str]],
    single_sample_sequence: Callable[[list[Any]], tuple[list[Any], list[str]]],
) -> str | None:
    if isinstance(value, dict):
        if looks_like_order_record(value):
            return "\n".join(order_table_lines([value], table_lines=table_lines, scalar_cell=scalar_cell, strategy_label=strategy_label))
        return order_sample_table_text(
            value,
            table_lines=table_lines,
            scalar_cell=scalar_cell,
            strategy_label=strategy_label,
            select_sample_part=select_sample_part,
            sample_note_lines=sample_note_lines,
            single_sample_sequence=single_sample_sequence,
        )
    if not isinstance(value, list) or not value:
        return None
    if not is_order_list(value):
        return None
    return "\n".join(order_table_lines(value, table_lines=table_lines, scalar_cell=scalar_cell, strategy_label=strategy_label))


def order_sample_table_text(
    value: Mapping[str, Any],
    *,
    table_lines: TableLines,
    scalar_cell: ScalarCell,
    strategy_label: StrategyLabel,
    select_sample_part: SelectSamplePart,
    sample_note_lines: Callable[[dict[str, Any], str], list[str]],
    single_sample_sequence: Callable[[list[Any]], tuple[list[Any], list[str]]],
) -> str | None:
    if value.get("type") not in {"list", "tuple", "set", "frozenset"}:
        return None
    sample = value.get("sample")
    if not isinstance(sample, dict):
        return None
    selected = select_sample_part(sample, lambda items: isinstance(items, list) and items and is_order_list(items))
    if selected is None:
        return None
    length = value.get("length")
    header = f"订单列表 length={length}" if length is not None else "订单列表"
    if value.get("truncated"):
        header = f"{header} truncated=True"
    lines = [header]
    lines.extend(sample_note_lines(sample, selected.name))
    items, row_notes = single_sample_sequence(selected.value)
    lines.extend(row_notes)
    lines.append(f"sample.{selected.name}:")
    lines.extend(order_table_lines(items, table_lines=table_lines, scalar_cell=scalar_cell, strategy_label=strategy_label, indent="  "))
    return "\n".join(lines)


def is_order_list(value: Sequence[Any]) -> bool:
    return all(isinstance(item, dict) and looks_like_order_record(item) for item in value)


def looks_like_order_record(value: Mapping[str, Any]) -> bool:
    required = {"instrument", "quantity", "intent_quantity", "status", "strategy", "timestamp"}
    return required <= set(value)


def order_table_lines(
    value: Sequence[Mapping[str, Any]],
    *,
    table_lines: TableLines,
    scalar_cell: ScalarCell,
    strategy_label: StrategyLabel,
    indent: str = "",
) -> list[str]:
    field_columns = order_field_columns(value)
    rows = []
    for item in value:
        fields = order_field_values(item)
        row: list[Any] = [
            scalar_cell(item.get("order_id")),
            strategy_label(item.get("strategy")),
            scalar_cell(item.get("timestamp")),
            scalar_cell(item.get("instrument")),
            scalar_cell(item.get("intent_quantity")),
            scalar_cell(item.get("quantity")),
            scalar_cell(item.get("status")),
            scalar_cell(item.get("reject_reason")),
        ]
        row.extend(scalar_cell(fields.get(field)) for field in field_columns)
        rows.append(tuple(row))
    return table_lines(
        (*ORDER_BASE_COLUMNS, *field_columns),
        rows,
        indent=indent,
        allow_transpose=False,
        allow_split=False,
    )


def order_record_key(item: Mapping[str, Any], fallback_index: int) -> str:
    order_id = item.get("order_id")
    if order_id not in (None, ""):
        return str(order_id)
    return "|".join(str(part) for part in (
        item.get("timestamp") or "",
        item.get("strategy") or "",
        item.get("instrument") or "",
        fallback_index,
    ))


def order_field_values(item: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(item, Mapping):
        return {}
    fields = item.get("fields")
    return dict(fields) if isinstance(fields, Mapping) else {}


def order_field_columns(items: Sequence[Mapping[str, Any] | None]) -> list[str]:
    field_seen: set[str] = set()
    for item in items:
        field_seen.update(order_field_values(item))
    field_columns = [field for field in ORDER_PREFERRED_FIELD_COLUMNS if field in field_seen]
    field_columns.extend(sorted(field_seen - set(field_columns)))
    return field_columns


def order_field_change_cell(before: Any, after: Any, *, scalar_cell: ScalarCell, change_cell: ChangeCell) -> str:
    before_text = scalar_cell(before)
    after_text = scalar_cell(after)
    if before_text == after_text:
        return after_text
    return change_cell(before_text, after_text)


def order_diff_text(
    before: Any,
    after: Any,
    *,
    table_lines: TableLines,
    scalar_cell: ScalarCell,
    change_cell: ChangeCell,
    highlight_cell: HighlightCell,
    strategy_label: StrategyLabel,
) -> str | None:
    before_list = [] if before is None else before
    after_list = [] if after is None else after
    if not isinstance(before_list, list) or not isinstance(after_list, list):
        return None
    if before_list and not is_order_list(before_list):
        return None
    if after_list and not is_order_list(after_list):
        return None
    if not before_list and not after_list:
        return "（无订单变化）"

    before_by_key = {order_record_key(item, index): item for index, item in enumerate(before_list) if isinstance(item, dict)}
    after_by_key = {order_record_key(item, index): item for index, item in enumerate(after_list) if isinstance(item, dict)}
    keys = [key for key in after_by_key]
    keys.extend(key for key in before_by_key if key not in after_by_key)

    field_columns = order_field_columns([
        *(before_by_key.get(key) for key in keys),
        *(after_by_key.get(key) for key in keys),
    ])

    rows: list[tuple[Any, ...]] = []
    for key in keys:
        before_item = before_by_key.get(key)
        after_item = after_by_key.get(key)
        display_item = after_item or before_item or {}
        before_fields = order_field_values(before_item)
        after_fields = order_field_values(after_item)
        if before_item is None:
            operation = "新增"
        elif after_item is None:
            operation = "删除"
        else:
            operation = "修改"
        row: list[Any] = [operation]
        for column in ORDER_BASE_COLUMNS:
            before_value = before_item.get(column) if isinstance(before_item, dict) else None
            after_value = after_item.get(column) if isinstance(after_item, dict) else None
            display_value = display_item.get(column) if isinstance(display_item, dict) else None
            if column == "strategy":
                before_value = strategy_label(before_value)
                after_value = strategy_label(after_value)
                display_value = strategy_label(display_value)
            if operation == "新增":
                row.append(highlight_cell(scalar_cell(after_value)))
            elif operation == "删除":
                row.append(highlight_cell(scalar_cell(before_value)))
            elif before_value != after_value:
                row.append(order_field_change_cell(before_value, after_value, scalar_cell=scalar_cell, change_cell=change_cell))
            else:
                row.append(scalar_cell(display_value))
        for field in field_columns:
            if operation == "新增":
                row.append(highlight_cell(scalar_cell(after_fields.get(field))))
            elif operation == "删除":
                row.append(highlight_cell(scalar_cell(before_fields.get(field))))
            else:
                row.append(order_field_change_cell(before_fields.get(field), after_fields.get(field), scalar_cell=scalar_cell, change_cell=change_cell))
        if operation in {"新增", "删除"}:
            row[0] = highlight_cell(operation)
        rows.append(tuple(row))

    if not rows:
        return "（无订单变化）"
    lines = [
        f"订单变化表 rows={len(rows)}（未截断；字段变化以黄色 before -> after 标识）"
    ]
    lines.extend(table_lines(("op", *ORDER_BASE_COLUMNS, *field_columns), rows, allow_transpose=False, allow_split=False))
    return "\n".join(lines)
