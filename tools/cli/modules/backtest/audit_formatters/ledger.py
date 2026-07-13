"""Ledger, cash-pool, and positions audit formatting helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from tools.cli.modules.backtest.audit_formatters import scope_tables


Normalize = Callable[[Any], Any]
DisplayFieldValue = Callable[[str, Any], Any]
ScalarCell = Callable[[Any], str]
ScalarSequenceText = Callable[[Sequence[Any]], str]
AuditText = Callable[[Any], str]
InlineComplexCellText = Callable[[Any], str]
TableCellIsComplex = Callable[[Any], bool]
ChangeCell = Callable[[Any, Any], str]
CashSummary = Callable[[Any], str]
TableLines = Callable[..., list[str]]


POSITION_SCALAR_COLUMNS: tuple[str, ...] = (
    "quantity",
    "average_cost",
    "settlement_price",
    "margin_reserved",
    "lots_count",
)


def ledger_scalar_text(
    value: Any,
    *,
    normalize: Normalize,
    scalar_sequence_text: ScalarSequenceText,
    audit_text: AuditText,
    inline_complex_cell_text: InlineComplexCellText,
    table_cell_is_complex: TableCellIsComplex,
) -> str | None:
    """Render a ledger-owned scalar compactly enough to fit table cells."""
    bracket_list_text = bracket_scalar_list_text(value, scalar_sequence_text=scalar_sequence_text)
    if bracket_list_text is not None:
        return bracket_list_text
    normalized = normalize(value)
    if isinstance(normalized, (list, tuple)) and all(not isinstance(item, (dict, list, tuple)) for item in normalized):
        return scalar_sequence_text(normalized)
    lines = audit_text(value).splitlines() or [""]
    if len(lines) != 1:
        return inline_complex_cell_text(value)
    if table_cell_is_complex(normalized):
        return inline_complex_cell_text(value)
    return lines[0]


def bracket_scalar_list_text(value: Any, *, scalar_sequence_text: ScalarSequenceText) -> str | None:
    """Render legacy stringified scalar lists like ``[A, B]`` as a sequence cell."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not (text.startswith("[") and text.endswith("]")):
        return None
    body = text[1:-1].strip()
    if not body:
        return "[]"
    if any(mark in body for mark in ("{", "}", "\n")):
        return None
    items = [item.strip().strip("'\"") for item in body.split(",") if item.strip()]
    if not items:
        return None
    return scalar_sequence_text(items)


def is_ledger_entries(entries: Sequence[Mapping[str, Any]]) -> bool:
    return scope_tables.is_scoped_entries(
        entries,
        required_dimensions=("ledger", "cash_pool"),
        allowed_record_scopes={"ledger", "ledger_config"},
    )


def is_cash_field(field_name: str) -> bool:
    return field_name.rsplit(".", 1)[-1] == "cash"


def cash_pool_group_key(entry: Mapping[str, Any], *values: str) -> tuple[str, ...]:
    return (*scope_tables.scope_route(entry, ("cash_pool",)), *values)


def join_entry_values(entries: Sequence[Mapping[str, Any]], key: str) -> str:
    values = [str(entry.get(key) or "") for entry in entries if entry.get(key) not in (None, "")]
    return ", ".join(sorted(dict.fromkeys(values))) if values else "无"


def join_entry_strategies(entries: Sequence[Mapping[str, Any]]) -> str:
    values = [
        str(strategy)
        for entry in entries
        for strategy in (entry.get("strategies") or [])
        if strategy not in (None, "")
    ]
    return ", ".join(sorted(dict.fromkeys(values))) if values else "无"


def ledger_entry_title(entry: Mapping[str, Any]) -> str:
    strategies = ", ".join(str(strategy) for strategy in (entry.get("strategies") or [])) or "无"
    return f"账本 {entry.get('ledger') or '?'} | 现金池 {entry.get('cash_pool') or '?'} | 策略 {strategies}"


def cash_pool_scalar_record_table(
    record: Mapping[str, Any],
    *,
    display_field_value: DisplayFieldValue,
    scalar_text: Callable[[Any], str | None],
) -> tuple[str, dict[tuple[str, str, str], str]] | None:
    field_name = str(record.get("field") or "")
    values = record.get("values") or []
    if not is_cash_field(field_name) or not is_ledger_entries(values):
        return None
    rows: dict[tuple[str, str, str], str] = {}
    for entry in values:
        if not isinstance(entry, Mapping):
            return None
        value_text = scalar_text(display_field_value(field_name, entry.get("value")))
        if value_text is None:
            return None
        route = (
            *scope_tables.scope_route(entry, ("cash_pool", "ledger")),
            ", ".join(str(strategy) for strategy in (entry.get("strategies") or [])) or "无",
        )
        rows[route] = value_text
    if not rows:
        return None
    return field_name.rsplit(".", 1)[-1], merge_cash_pool_routes(rows)


def merge_cash_pool_routes(rows: Mapping[tuple[str, str, str], str]) -> dict[tuple[str, str, str], str]:
    grouped: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for (cash_pool, ledger, strategies), value in rows.items():
        grouped.setdefault((cash_pool, value), []).append((ledger, strategies))
    return {
        (
            cash_pool,
            ", ".join(sorted(dict.fromkeys(ledger for ledger, _ in entries))),
            ", ".join(
                sorted(dict.fromkeys(
                    strategy
                    for _, strategies in entries
                    for strategy in strategies.split(", ")
                    if strategy and strategy != "无"
                ))
            ) or "无",
        ): value
        for (cash_pool, value), entries in grouped.items()
    }


def ledger_scalar_record_table(
    record: Mapping[str, Any],
    *,
    display_field_value: DisplayFieldValue,
    scalar_text: Callable[[Any], str | None],
) -> tuple[str, dict[tuple[str, str, str], str]] | None:
    field_name = str(record.get("field") or "")
    values = record.get("values") or []
    if is_cash_field(field_name) or not is_ledger_entries(values):
        return None
    rows: dict[tuple[str, str, str], str] = {}
    for entry in values:
        if not isinstance(entry, Mapping):
            return None
        value_text = scalar_text(display_field_value(field_name, entry.get("value")))
        if value_text is None:
            return None
        route = (
            *scope_tables.scope_route(entry, ("ledger", "cash_pool")),
            ", ".join(str(strategy) for strategy in (entry.get("strategies") or [])) or "无",
        )
        rows[route] = value_text
    if not rows:
        return None
    return field_name.rsplit(".", 1)[-1], rows


def ledger_scalar_value_rows(
    field_name: str,
    values: Sequence[Mapping[str, Any]],
    *,
    display_field_value: DisplayFieldValue,
    scalar_text: Callable[[Any], str | None],
) -> tuple[tuple[str, ...], list[tuple[Any, ...]]] | None:
    if not is_ledger_entries(values):
        return None
    table = (
        cash_pool_scalar_record_table(
            {"field": field_name, "values": list(values)},
            display_field_value=display_field_value,
            scalar_text=scalar_text,
        )
        if is_cash_field(field_name)
        else ledger_scalar_record_table(
            {"field": field_name, "values": list(values)},
            display_field_value=display_field_value,
            scalar_text=scalar_text,
        )
    )
    if table is None:
        return None
    _field_column, route_values = table
    if is_cash_field(field_name):
        headers = ("cash pool", "ledgers", "strategies", "value")
    else:
        headers = ("ledger", "cash pool", "strategies", "value")
    rows = [(*route, value) for route, value in route_values.items()]
    return headers, sorted(rows)


def cash_pool_scalar_change_record_table(
    field_name: str,
    changes: Sequence[Mapping[str, Any]],
    *,
    display_field_value: DisplayFieldValue,
    scalar_text: Callable[[Any], str | None],
    change_cell: ChangeCell,
) -> tuple[str, dict[tuple[str, str, str], str]] | None:
    if not is_cash_field(field_name) or not is_ledger_entries(changes):
        return None
    raw_rows: dict[tuple[str, str, str], str] = {}
    for change in changes:
        before_text = scalar_text(display_field_value(field_name, change.get("before")))
        after_text = scalar_text(display_field_value(field_name, change.get("after")))
        if before_text is None or after_text is None:
            return None
        route = (
            *scope_tables.scope_route(change, ("cash_pool", "ledger")),
            ", ".join(str(strategy) for strategy in (change.get("strategies") or [])) or "无",
        )
        raw_rows[route] = change_cell(before_text, after_text)
    return field_name.rsplit(".", 1)[-1], merge_cash_pool_routes(raw_rows)


def ledger_scalar_change_record_table(
    field_name: str,
    changes: Sequence[Mapping[str, Any]],
    *,
    display_field_value: DisplayFieldValue,
    scalar_text: Callable[[Any], str | None],
    change_cell: ChangeCell,
) -> tuple[str, dict[tuple[str, str, str], str]] | None:
    if is_cash_field(field_name) or not is_ledger_entries(changes):
        return None
    rows: dict[tuple[str, str, str], str] = {}
    for change in changes:
        before_text = scalar_text(display_field_value(field_name, change.get("before")))
        after_text = scalar_text(display_field_value(field_name, change.get("after")))
        if before_text is None or after_text is None:
            return None
        route = (
            *scope_tables.scope_route(change, ("ledger", "cash_pool")),
            ", ".join(str(strategy) for strategy in (change.get("strategies") or [])) or "无",
        )
        rows[route] = change_cell(before_text, after_text)
    return field_name.rsplit(".", 1)[-1], rows


def ledger_scalar_change_rows(
    field_name: str,
    changes: Sequence[Mapping[str, Any]],
    *,
    display_field_value: DisplayFieldValue,
    scalar_text: Callable[[Any], str | None],
    change_cell: ChangeCell,
) -> tuple[tuple[str, ...], list[tuple[Any, ...]]] | None:
    if not is_ledger_entries(changes):
        return None
    if is_cash_field(field_name):
        return None
    table = ledger_scalar_change_record_table(
        field_name,
        changes,
        display_field_value=display_field_value,
        scalar_text=scalar_text,
        change_cell=change_cell,
    )
    if table is None:
        return None
    _field_column, route_values = table
    rows = [(*route, value) for route, value in route_values.items()]
    return ("ledger", "cash pool", "strategies", "change"), sorted(rows)


def cash_pool_scalar_change_rows(
    field_name: str,
    changes: Sequence[Mapping[str, Any]],
    *,
    display_field_value: DisplayFieldValue,
    scalar_text: Callable[[Any], str | None],
    change_cell: ChangeCell,
) -> tuple[tuple[str, ...], list[tuple[Any, ...]]] | None:
    table = cash_pool_scalar_change_record_table(
        field_name,
        changes,
        display_field_value=display_field_value,
        scalar_text=scalar_text,
        change_cell=change_cell,
    )
    if table is None:
        return None
    field_column, route_values = table
    rows = [(*route, value) for route, value in route_values.items()]
    return ("cash pool", "ledgers", "strategies", field_column), sorted(rows)


def combined_scalar_value_rows(
    tables: Sequence[tuple[str, Mapping[tuple[str, str, str], str]]],
) -> tuple[list[str], list[tuple[Any, ...]]] | None:
    """Return columns/rows for combined ledger or cash-pool scalar value tables."""
    return scope_tables.combine_route_value_maps(tables)


def normalized_positions(value: Any, *, normalize: Normalize) -> dict[str, dict[str, Any]] | None:
    if isinstance(value, Mapping) and value.get("type") == "PositionsTable":
        positions = value.get("positions")
        return dict(positions) if isinstance(positions, Mapping) else {}
    normalized = normalize(value)
    if normalized in (None, ""):
        return {}
    if not isinstance(normalized, Mapping):
        return None
    positions: dict[str, dict[str, Any]] = {}
    for product, payload in normalized.items():
        if not isinstance(payload, Mapping):
            return None
        row = dict(payload)
        row["lots_count"] = lots_count(row.get("lots"))
        positions[str(product)] = row
    return positions


def positions_summary(value: Any, *, normalize: Normalize) -> dict[str, Any] | None:
    positions = normalized_positions(value, normalize=normalize)
    if positions is None:
        return None
    return {"type": "PositionsTable", "positions": positions}


def lots_count(value: Any) -> int | str:
    if value in (None, ""):
        return 0
    if isinstance(value, Mapping):
        if value.get("type") in {"deque", "list", "tuple", "set", "frozenset"} and value.get("length") is not None:
            return value.get("length")
        if isinstance(value.get("sample"), list) and value.get("truncated"):
            return f"{value.get('length', len(value.get('sample') or []))}+"
        return len(value)
    if isinstance(value, (list, tuple, set, frozenset)):
        return len(value)
    return "?"


def positions_text(
    value: Mapping[str, Any],
    *,
    table_lines: TableLines,
    scalar_cell: ScalarCell,
    normalize: Normalize,
    cash_summary: CashSummary,
) -> str:
    positions = normalized_positions(value, normalize=normalize)
    if positions is None:
        return ""
    if not positions:
        return "positions: (empty)"
    rows = grouped_position_rows(positions, scalar_cell=scalar_cell, cash_summary=cash_summary)
    return "\n".join(table_lines(("products", *POSITION_SCALAR_COLUMNS), rows, allow_transpose=False))


def grouped_position_rows(
    positions: Mapping[str, Mapping[str, Any]],
    *,
    scalar_cell: ScalarCell,
    cash_summary: CashSummary,
) -> list[tuple[Any, ...]]:
    grouped: dict[tuple[str, ...], list[str]] = {}
    row_values: dict[tuple[str, ...], tuple[str, ...]] = {}
    for product, payload in sorted(positions.items()):
        values = tuple(position_scalar(payload, column, scalar_cell=scalar_cell, cash_summary=cash_summary) for column in POSITION_SCALAR_COLUMNS)
        grouped.setdefault(values, []).append(product)
        row_values[values] = values
    rows: list[tuple[Any, ...]] = []
    all_products = sorted(positions)
    for values, products in sorted(grouped.items(), key=lambda item: item[1][0]):
        rows.append((product_list_cell(products, all_products=all_products), *row_values[values]))
    return rows


def product_list_cell(products: Sequence[str], *, all_products: Sequence[str] | None = None) -> str:
    if all_products and len(products) > 1 and set(products) == set(all_products):
        return "全部产品"
    if len(products) <= 6:
        return ", ".join(products)
    head = ", ".join(products[:3])
    return f"{head}, ..."


def position_scalar(
    payload: Mapping[str, Any],
    column: str,
    *,
    scalar_cell: ScalarCell,
    cash_summary: CashSummary,
) -> str:
    if column == "lots_count":
        return scalar_cell(payload.get("lots_count"))
    value = payload.get(column)
    if column == "margin_reserved" and isinstance(value, Mapping):
        return cash_summary(value)
    return scalar_cell(value)


def positions_diff_text(
    before: Any,
    after: Any,
    *,
    table_lines: TableLines,
    scalar_cell: ScalarCell,
    normalize: Normalize,
    cash_summary: CashSummary,
    change_cell: ChangeCell,
) -> str | None:
    rows = positions_diff_rows(
        before,
        after,
        scalar_cell=scalar_cell,
        normalize=normalize,
        cash_summary=cash_summary,
        change_cell=change_cell,
    )
    if rows is None:
        return None
    if not rows:
        return "（无变化）"
    if all(not row[-1] for row in rows):
        headers: tuple[str, ...] = ("products", *POSITION_SCALAR_COLUMNS)
        rows = [row[:-1] for row in rows]
    else:
        headers = ("products", *POSITION_SCALAR_COLUMNS, "lot changes")
    return "\n".join(table_lines(headers, rows, allow_transpose=False))


def positions_diff_rows(
    before: Any,
    after: Any,
    *,
    scalar_cell: ScalarCell,
    normalize: Normalize,
    cash_summary: CashSummary,
    change_cell: ChangeCell,
) -> list[tuple[str, ...]] | None:
    before_is_positions = isinstance(before, Mapping) and before.get("type") == "PositionsTable"
    after_is_positions = isinstance(after, Mapping) and after.get("type") == "PositionsTable"
    if not (before_is_positions or after_is_positions):
        return None
    before_positions = normalized_positions(before, normalize=normalize)
    after_positions = normalized_positions(after, normalize=normalize)
    if before_positions is None or after_positions is None:
        return None
    all_products = sorted(set(before_positions) | set(after_positions))
    grouped: dict[tuple[str, ...], list[str]] = {}
    for product in all_products:
        before_payload = before_positions.get(product)
        after_payload = after_positions.get(product)
        if before_payload == after_payload:
            continue
        row = position_diff_values(
            before_payload,
            after_payload,
            scalar_cell=scalar_cell,
            cash_summary=cash_summary,
            change_cell=change_cell,
        )
        grouped.setdefault(row, []).append(product)
    return [
        (product_list_cell(group_products, all_products=all_products), *values)
        for values, group_products in sorted(grouped.items(), key=lambda item: item[1][0])
    ]


def position_diff_values(
    before_payload: Mapping[str, Any] | None,
    after_payload: Mapping[str, Any] | None,
    *,
    scalar_cell: ScalarCell,
    cash_summary: CashSummary,
    change_cell: ChangeCell,
) -> tuple[str, ...]:
    cells: list[str] = []
    for column in POSITION_SCALAR_COLUMNS:
        before_value = position_scalar(before_payload or {}, column, scalar_cell=scalar_cell, cash_summary=cash_summary)
        after_value = position_scalar(after_payload or {}, column, scalar_cell=scalar_cell, cash_summary=cash_summary)
        cells.append("" if before_value == after_value else change_cell(before_value, after_value))
    return (*cells, lot_change_summary(before_payload, after_payload, change_cell=change_cell))


def lot_change_summary(
    before_payload: Mapping[str, Any] | None,
    after_payload: Mapping[str, Any] | None,
    *,
    change_cell: ChangeCell,
) -> str:
    before_lots = (before_payload or {}).get("lots")
    after_lots = (after_payload or {}).get("lots")
    if before_lots == after_lots:
        return ""
    before_count = lots_count(before_lots)
    after_count = lots_count(after_lots)
    before_sequence = lot_sequence(before_lots)
    after_sequence = lot_sequence(after_lots)
    if before_sequence is not None and after_sequence is not None:
        changed = changed_lot_count(before_sequence, after_sequence)
        if changed == 0:
            return ""
        return f"{change_cell(before_count, after_count)}; changed lots {changed}"
    return change_cell(before_count, after_count)


def lot_sequence(value: Any) -> list[Any] | None:
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, Mapping) and value.get("type") in {"deque", "list", "tuple"}:
        sample = value.get("sample")
        if isinstance(sample, list) and not value.get("truncated"):
            return sample
    return None


def changed_lot_count(before_lots: Sequence[Any], after_lots: Sequence[Any]) -> int:
    count = abs(len(after_lots) - len(before_lots))
    for before_item, after_item in zip(before_lots, after_lots, strict=False):
        if before_item != after_item:
            count += 1
    return count


def positions_value_rows(
    field_name: str,
    values: Sequence[Mapping[str, Any]],
    *,
    display_field_value: DisplayFieldValue,
    normalize: Normalize,
    scalar_cell: ScalarCell,
    cash_summary: CashSummary,
) -> tuple[tuple[str, ...], list[tuple[Any, ...]]] | None:
    if field_name != "LedgerModule.positions" and field_name.rsplit(".", 1)[-1] != "positions":
        return None
    if not is_ledger_entries(values):
        return None
    rows: list[tuple[Any, ...]] = []
    for entry in values:
        display_value = display_field_value(field_name, entry.get("value"))
        positions = normalized_positions(display_value, normalize=normalize)
        if positions is None:
            return None
        strategies = ", ".join(str(strategy) for strategy in (entry.get("strategies") or [])) or "无"
        position_rows = (
            grouped_position_rows(positions, scalar_cell=scalar_cell, cash_summary=cash_summary)
            if positions
            else [("全部产品", "null", "null", "null", "null", "0")]
        )
        for row in position_rows:
            rows.append((
                *scope_tables.scope_route(entry, ("ledger", "cash_pool")),
                strategies,
                *row,
            ))
    headers = ("ledger", "cash pool", "strategies", "products", *POSITION_SCALAR_COLUMNS)
    return headers, sorted(rows)


def positions_change_rows(
    field_name: str,
    changes: Sequence[Mapping[str, Any]],
    *,
    display_field_value: DisplayFieldValue,
    normalize: Normalize,
    scalar_cell: ScalarCell,
    cash_summary: CashSummary,
    change_cell: ChangeCell,
) -> tuple[tuple[str, ...], list[tuple[Any, ...]]] | None:
    if field_name != "LedgerModule.positions" and field_name.rsplit(".", 1)[-1] != "positions":
        return None
    if not is_ledger_entries(changes):
        return None
    wide_rows: list[tuple[Any, ...]] = []
    for change in changes:
        before = display_field_value(field_name, change.get("before"))
        after = display_field_value(field_name, change.get("after"))
        position_rows = positions_diff_rows(
            before,
            after,
            normalize=normalize,
            scalar_cell=scalar_cell,
            cash_summary=cash_summary,
            change_cell=change_cell,
        )
        if position_rows is None:
            return None
        strategies = ", ".join(str(strategy) for strategy in (change.get("strategies") or [])) or "无"
        for row in position_rows:
            wide_rows.append((
                *scope_tables.scope_route(change, ("ledger", "cash_pool")),
                strategies,
                *row,
            ))
    if not wide_rows:
        return ("ledger", "cash pool", "strategies", "products"), []
    base_headers = ("ledger", "cash pool", "strategies", "products")
    value_headers = (*POSITION_SCALAR_COLUMNS, "lot changes")
    kept_value_indexes = [
        index
        for index, header in enumerate(value_headers)
        if header != "lot changes" and any(row[len(base_headers) + index] not in ("", "null -> null") for row in wide_rows)
    ]
    if any(row[-1] for row in wide_rows):
        kept_value_indexes.append(len(value_headers) - 1)
    headers = (*base_headers, *[value_headers[index] for index in kept_value_indexes])
    compact_rows = [
        tuple([*row[:len(base_headers)], *[row[len(base_headers) + index] for index in kept_value_indexes]])
        for row in wide_rows
    ]
    return headers, sorted(compact_rows)
