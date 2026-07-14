"""Event and event-payload audit formatting helpers."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any


TableLines = Callable[..., list[str]]
AuditText = Callable[[Any], str]
TableCellIsComplex = Callable[[Any], bool]
SelectSamplePart = Callable[[dict[str, Any], Any], Any]
DedupeValues = Callable[[list[Any]], list[Any]]
ScalarCell = Callable[[Any], str]
ChangeCell = Callable[[Any, Any], str]
HighlightCell = Callable[[str], str]

EVENT_DRAFT_TIMESTAMP_SAMPLE_LIMIT = 10
EVENT_DRAFT_TIMESTAMP_SAMPLE_HEAD = 5
EVENT_DRAFT_TIMESTAMP_SAMPLE_TAIL = 5


def lifecycle_notice_change_diff(
    field_name: str,
    changes: list[dict[str, Any]],
    *,
    display_field_value: Callable[[str, Any], Any],
    dedupe: DedupeValues,
) -> tuple[str, Any, Any] | None:
    short_name = field_name.rsplit(".", 1)[-1]
    if short_name not in {"force_close_notices", "rollover_notices"}:
        return None
    context_changes = [change for change in changes if str(change.get("scope") or "") == "context"]
    selected = context_changes[:1] or changes
    label = "合并事件草稿（所有 active strategies）"
    if len(selected) == 1:
        change = selected[0]
        return (
            label,
            display_field_value(field_name, change.get("before")),
            display_field_value(field_name, change.get("after")),
        )

    before_items: list[Any] = []
    after_items: list[Any] = []
    for change in selected:
        before = change.get("before")
        after = change.get("after")
        if isinstance(before, list):
            before_items.extend(before)
        elif before not in (None, ""):
            before_items.append(before)
        if isinstance(after, list):
            after_items.extend(after)
        elif after not in (None, ""):
            after_items.append(after)
    return label, dedupe(before_items), dedupe(after_items)


def strategy_routes(data: Mapping[str, Any]) -> dict[str, tuple[tuple[str, str], ...]]:
    routes: dict[str, list[tuple[str, str]]] = {}
    ledgers = data.get("ledgers_before") or data.get("ledgers_after") or []
    if not isinstance(ledgers, list):
        return {}
    for ledger in ledgers:
        if not isinstance(ledger, Mapping):
            continue
        ledger_id = str(ledger.get("ledger") or "?")
        cash_pool = str(ledger.get("cash_pool") or "?")
        strategies = ledger.get("strategies")
        if not isinstance(strategies, list):
            continue
        for strategy in strategies:
            strategy_text = str(strategy or "").strip()
            if not strategy_text:
                continue
            route = (ledger_id, cash_pool)
            if route not in routes.setdefault(strategy_text, []):
                routes[strategy_text].append(route)
    return {strategy: tuple(route_list) for strategy, route_list in routes.items()}


def event_product_filter(data: Mapping[str, Any]) -> tuple[str, ...]:
    values: list[Any] = []
    current_event = data.get("current_event")
    if isinstance(current_event, Mapping):
        subjects = current_event.get("subjects")
        if isinstance(subjects, list):
            for subject in subjects:
                if not isinstance(subject, Mapping):
                    continue
                for key in ("subject", "product", "contract", "instrument", "contract_product"):
                    values.append(subject.get(key))
                payload = subject.get("payload")
                if isinstance(payload, Mapping):
                    values.extend(payload_product_values(payload))
    for collection_name in ("event_payloads", "event_payload_changes"):
        collection = data.get(collection_name)
        if isinstance(collection, list):
            for item in collection:
                if isinstance(item, Mapping):
                    values.extend(payload_product_values(item))
                    payload = item.get("payload")
                    if isinstance(payload, Mapping):
                        values.extend(payload_product_values(payload))
    return tuple(dict.fromkeys(key for value in values for key in product_filter_keys(value)))


def payload_product_values(payload: Mapping[str, Any]) -> list[Any]:
    values = []
    for key in ("subject", "product", "contract", "instrument", "contract_product", "uid"):
        values.append(payload.get(key))
    order = payload.get("order")
    if isinstance(order, Mapping):
        values.extend(payload_product_values(order))
    return values


def product_filter_keys(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    keys = [text]
    if "|" in text:
        parts = text.split("|")
        if len(parts) >= 4:
            exchange = parts[0].upper()
            root = parts[2].upper()
            suffix = {
                "CZCE": "CZC",
                "DCE": "DCE",
                "GFEX": "GFE",
                "GFE": "GFE",
                "SHFE": "SHF",
                "INE": "INE",
                "CFFEX": "CFE",
            }.get(exchange, exchange)
            keys.append(f"{root}.{suffix}")
    return keys


def event_draft_table_text(
    value: Any,
    *,
    table_lines: TableLines,
    table_cell_is_complex: TableCellIsComplex,
    notice_scalar: Callable[[Any], str],
    highlight_cell: HighlightCell | None = None,
    highlight_rows: bool = False,
) -> str | None:
    if isinstance(value, dict):
        return None
    if not isinstance(value, list) or not value:
        return None
    if not is_event_draft_list(value):
        return None
    return "\n".join(event_draft_table_lines(
        value,
        table_lines=table_lines,
        table_cell_is_complex=table_cell_is_complex,
        notice_scalar=notice_scalar,
        highlight_cell=highlight_cell,
        highlight_rows=highlight_rows,
    ))


def event_draft_diff_table_text(
    before: Any,
    after: Any,
    *,
    table_lines: TableLines,
    table_cell_is_complex: TableCellIsComplex,
    notice_scalar: Callable[[Any], str],
    scalar_cell: ScalarCell,
    change_cell: ChangeCell,
    highlight_cell: HighlightCell,
) -> str | None:
    before_list = [] if before is None else before
    after_list = [] if after is None else after
    if not isinstance(before_list, list) or not isinstance(after_list, list):
        return None
    if before_list and not is_event_draft_list(before_list):
        return None
    if after_list and not is_event_draft_list(after_list):
        return None
    if not before_list and not after_list:
        return "（无事件变化）"
    order_lines = order_event_draft_diff_table_lines(
        before_list,
        after_list,
        table_lines=table_lines,
        scalar_cell=scalar_cell,
        change_cell=change_cell,
        highlight_cell=highlight_cell,
    )
    if order_lines is not None:
        return "\n".join(order_lines)
    return "\n".join(generic_event_draft_diff_table_lines(
        before_list,
        after_list,
        table_lines=table_lines,
        table_cell_is_complex=table_cell_is_complex,
        notice_scalar=notice_scalar,
        scalar_cell=scalar_cell,
        change_cell=change_cell,
        highlight_cell=highlight_cell,
    ))


def event_draft_sample_table_text(
    value: Mapping[str, Any],
    *,
    table_lines: TableLines,
    table_cell_is_complex: TableCellIsComplex,
    notice_scalar: Callable[[Any], str],
    select_sample_part: SelectSamplePart,
    sample_note_lines: Callable[[dict[str, Any], str], list[str]],
    single_sample_sequence: Callable[[list[Any]], tuple[list[Any], list[str]]],
) -> str | None:
    if value.get("type") not in {"list", "tuple", "set", "frozenset"}:
        return None
    sample = value.get("sample")
    if not isinstance(sample, dict):
        return None
    selected = select_sample_part(sample, lambda items: isinstance(items, list) and items and is_event_draft_list(items))
    if selected is None:
        return None
    length = value.get("length")
    header = f"事件草稿列表 length={length}" if length is not None else "事件草稿列表"
    if value.get("truncated"):
        header = f"{header} truncated=True"
    lines = [header]
    lines.extend(sample_note_lines(sample, selected.name))
    items, row_notes = single_sample_sequence(selected.value)
    lines.extend(row_notes)
    lines.append(f"sample.{selected.name}:")
    lines.extend(event_draft_table_lines(
        items,
        indent="  ",
        table_lines=table_lines,
        table_cell_is_complex=table_cell_is_complex,
        notice_scalar=notice_scalar,
    ))
    return "\n".join(lines)


def is_event_draft_list(value: Sequence[Any]) -> bool:
    return all(isinstance(item, Mapping) and item.get("type") == "EventDraft" for item in value)


def event_draft_table_lines(
    value: Sequence[Mapping[str, Any]],
    *,
    table_lines: TableLines,
    table_cell_is_complex: TableCellIsComplex,
    notice_scalar: Callable[[Any], str],
    indent: str = "",
    highlight_cell: HighlightCell | None = None,
    highlight_rows: bool = False,
) -> list[str]:
    value, sample_note = sample_event_drafts_by_timestamp(value)
    lifecycle_notice_lines = lifecycle_notice_table_lines(
        value,
        table_lines=table_lines,
        table_cell_is_complex=table_cell_is_complex,
        notice_scalar=notice_scalar,
        indent=indent,
        highlight_cell=highlight_cell,
        highlight_rows=highlight_rows,
    )
    if lifecycle_notice_lines is not None:
        return [*sample_note, *lifecycle_notice_lines]
    order_lines = order_event_draft_table_lines(
        value,
        table_lines=table_lines,
        indent=indent,
        highlight_cell=highlight_cell,
        highlight_rows=highlight_rows,
    )
    if order_lines is not None:
        return [*sample_note, *order_lines]
    rows = []
    for item in value:
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        details = event_payload_details(payload)
        route = item.get("strategy") or item.get("ledger") or ""
        row = (
            item.get("timestamp") or "",
            item.get("kind") or payload.get("kind") or "",
            route,
            payload.get("product") or payload.get("ledger_id") or payload.get("trading_day") or "",
            payload.get("notice_type") or payload.get("kind") or "",
            payload.get("notice_reason") or payload.get("reason") or "",
            details if details else "",
        )
        rows.append(highlight_row(row, highlight_cell=highlight_cell) if highlight_rows else row)
    return [
        *sample_note,
        *table_lines(
            ("timestamp", "event", "route", "subject", "action", "reason", "details"),
            rows,
            indent=indent,
        ),
    ]


def order_event_draft_table_lines(
    value: Sequence[Mapping[str, Any]],
    *,
    table_lines: TableLines,
    indent: str = "",
    highlight_cell: HighlightCell | None = None,
    highlight_rows: bool = False,
) -> list[str] | None:
    rows = []
    for item in value:
        payload = item.get("payload") if isinstance(item.get("payload"), Mapping) else {}
        if str(item.get("kind") or payload.get("kind") or "").lower() != "order":
            return None
        if not looks_like_order_payload(payload):
            return None
        row = (
            "新增",
            item.get("timestamp") or payload.get("timestamp") or "",
            item.get("kind") or payload.get("kind") or "",
            item.get("strategy") or payload.get("strategy") or "",
            payload.get("order_id") or "",
            payload.get("instrument") or "",
            payload.get("intent_quantity"),
            payload.get("quantity"),
            payload.get("status") or "",
            payload.get("reject_reason") or "",
            payload.get("price_timestamp") or "",
        )
        rows.append(highlight_row(row, highlight_cell=highlight_cell) if highlight_rows else row)
    if not rows:
        return None
    return [
        f"{indent}事件新增表 rows={len(rows)}",
        *table_lines(
            (
                "op",
                "event_time",
                "event_kind",
                "strategy",
                "order_id",
                "instrument",
                "intent_quantity",
                "quantity",
                "status",
                "reject_reason",
                "price_timestamp",
            ),
            rows,
            indent=indent,
            allow_transpose=False,
            allow_split=False,
        ),
    ]


def looks_like_order_payload(value: Mapping[str, Any]) -> bool:
    required = {"instrument", "quantity", "intent_quantity", "status", "strategy", "timestamp", "order_id"}
    return required <= set(value)


def order_event_draft_diff_table_lines(
    before: Sequence[Mapping[str, Any]],
    after: Sequence[Mapping[str, Any]],
    *,
    table_lines: TableLines,
    scalar_cell: ScalarCell,
    change_cell: ChangeCell,
    highlight_cell: HighlightCell,
) -> list[str] | None:
    if before and order_event_draft_table_lines(before, table_lines=table_lines) is None:
        return None
    if after and order_event_draft_table_lines(after, table_lines=table_lines) is None:
        return None
    before_by_key = {event_draft_key(item, index): item for index, item in enumerate(before)}
    after_by_key = {event_draft_key(item, index): item for index, item in enumerate(after)}
    keys = [key for key in after_by_key]
    keys.extend(key for key in before_by_key if key not in after_by_key)
    rows: list[tuple[Any, ...]] = []
    for key in keys:
        before_item = before_by_key.get(key)
        after_item = after_by_key.get(key)
        operation = "新增" if before_item is None else "删除" if after_item is None else "修改"
        row = order_event_draft_diff_row(
            before_item,
            after_item,
            operation=operation,
            scalar_cell=scalar_cell,
            change_cell=change_cell,
            highlight_cell=highlight_cell,
        )
        if row is not None:
            rows.append(row)
    if not rows:
        return ["（无事件变化）"]
    total_rows = len(rows)
    rows, sample_note = sample_rows_by_event_time(rows, time_index=1)
    return [
        *sample_note,
        f"订单事件变化表 rows={total_rows}（字段变化以黄色 before -> after 标识）",
        *table_lines(
            (
                "op",
                "event_time",
                "event_kind",
                "strategy",
                "order_id",
                "instrument",
                "intent_quantity",
                "quantity",
                "status",
                "reject_reason",
                "price_timestamp",
            ),
            rows,
            allow_transpose=False,
            allow_split=False,
        ),
    ]


def order_event_draft_diff_row(
    before_item: Mapping[str, Any] | None,
    after_item: Mapping[str, Any] | None,
    *,
    operation: str,
    scalar_cell: ScalarCell,
    change_cell: ChangeCell,
    highlight_cell: HighlightCell,
) -> tuple[Any, ...] | None:
    display_item = after_item or before_item
    if display_item is None:
        return None
    before_payload = before_item.get("payload") if isinstance(before_item, Mapping) and isinstance(before_item.get("payload"), Mapping) else {}
    after_payload = after_item.get("payload") if isinstance(after_item, Mapping) and isinstance(after_item.get("payload"), Mapping) else {}
    display_payload = display_item.get("payload") if isinstance(display_item.get("payload"), Mapping) else {}
    columns = (
        lambda item, payload: item.get("timestamp") or payload.get("timestamp") or "",
        lambda item, payload: item.get("kind") or payload.get("kind") or "",
        lambda item, payload: item.get("strategy") or payload.get("strategy") or "",
        lambda item, payload: payload.get("order_id") or "",
        lambda item, payload: payload.get("instrument") or "",
        lambda item, payload: payload.get("intent_quantity"),
        lambda item, payload: payload.get("quantity"),
        lambda item, payload: payload.get("status") or "",
        lambda item, payload: payload.get("reject_reason") or "",
        lambda item, payload: payload.get("price_timestamp") or "",
    )
    row: list[Any] = [operation]
    for getter in columns:
        before_value = getter(before_item, before_payload) if before_item is not None else None
        after_value = getter(after_item, after_payload) if after_item is not None else None
        display_value = getter(display_item, display_payload)
        if operation == "新增":
            row.append(highlight_cell(scalar_cell(after_value)))
        elif operation == "删除":
            row.append(highlight_cell(scalar_cell(before_value)))
        elif before_value != after_value:
            row.append(change_cell(scalar_cell(before_value), scalar_cell(after_value)))
        else:
            row.append(scalar_cell(display_value))
    if operation in {"新增", "删除"}:
        row[0] = highlight_cell(operation)
    return tuple(row)


def generic_event_draft_diff_table_lines(
    before: Sequence[Mapping[str, Any]],
    after: Sequence[Mapping[str, Any]],
    *,
    table_lines: TableLines,
    table_cell_is_complex: TableCellIsComplex,
    notice_scalar: Callable[[Any], str],
    scalar_cell: ScalarCell,
    change_cell: ChangeCell,
    highlight_cell: HighlightCell,
) -> list[str]:
    before_by_key = {event_draft_key(item, index): item for index, item in enumerate(before)}
    after_by_key = {event_draft_key(item, index): item for index, item in enumerate(after)}
    keys = [key for key in after_by_key]
    keys.extend(key for key in before_by_key if key not in after_by_key)
    rows: list[tuple[Any, ...]] = []
    for key in keys:
        before_item = before_by_key.get(key)
        after_item = after_by_key.get(key)
        operation = "新增" if before_item is None else "删除" if after_item is None else "修改"
        before_row = generic_event_draft_row(before_item, table_cell_is_complex=table_cell_is_complex, notice_scalar=notice_scalar)
        after_row = generic_event_draft_row(after_item, table_cell_is_complex=table_cell_is_complex, notice_scalar=notice_scalar)
        display_row = after_row or before_row
        if display_row is None:
            continue
        if operation in {"新增", "删除"}:
            rows.append(tuple([highlight_cell(operation), *[highlight_cell(scalar_cell(cell)) for cell in display_row]]))
            continue
        row = [operation]
        for before_cell, after_cell in zip(before_row or (), after_row or (), strict=False):
            before_text = scalar_cell(before_cell)
            after_text = scalar_cell(after_cell)
            row.append(change_cell(before_text, after_text) if before_text != after_text else after_text)
        rows.append(tuple(row))
    total_rows = len(rows)
    rows, sample_note = sample_rows_by_event_time(rows, time_index=1)
    return [
        *sample_note,
        f"事件变化表 rows={total_rows}（字段变化以黄色 before -> after 标识）",
        *table_lines(("op", "timestamp", "event", "route", "subject", "action", "reason", "details"), rows, allow_transpose=False),
    ]


def generic_event_draft_row(
    item: Mapping[str, Any] | None,
    *,
    table_cell_is_complex: TableCellIsComplex,
    notice_scalar: Callable[[Any], str],
) -> tuple[Any, ...] | None:
    if item is None:
        return None
    payload = item.get("payload") if isinstance(item.get("payload"), Mapping) else {}
    details = event_payload_details(payload)
    route = item.get("strategy") or item.get("ledger") or ""
    return (
        item.get("timestamp") or "",
        item.get("kind") or payload.get("kind") or "",
        route,
        payload.get("product") or payload.get("ledger_id") or payload.get("trading_day") or "",
        payload.get("notice_type") or payload.get("kind") or "",
        payload.get("notice_reason") or payload.get("reason") or "",
        details if details and not table_cell_is_complex(details) else notice_scalar(details) if details else "",
    )


def event_draft_key(item: Mapping[str, Any], fallback_index: int) -> str:
    payload = item.get("payload") if isinstance(item.get("payload"), Mapping) else {}
    order_id = payload.get("order_id")
    if order_id not in (None, ""):
        return f"order:{order_id}"
    index_key = item.get("index_key")
    if index_key not in (None, ""):
        return f"index:{index_key}"
    return "|".join(str(part) for part in (
        item.get("timestamp") or "",
        item.get("kind") or "",
        item.get("strategy") or "",
        item.get("ledger") or "",
        payload.get("kind") or payload.get("notice_type") or "",
        payload.get("product") or payload.get("ledger_id") or payload.get("trading_day") or "",
        fallback_index,
    ))


def highlight_row(row: Sequence[Any], *, highlight_cell: HighlightCell | None) -> tuple[Any, ...]:
    if highlight_cell is None:
        return tuple(row)
    return tuple(highlight_cell(str(cell)) for cell in row)


def sample_event_drafts_by_timestamp(value: Sequence[Mapping[str, Any]]) -> tuple[list[Mapping[str, Any]], list[str]]:
    timestamps = list(dict.fromkeys(str(item.get("timestamp") or "") for item in value))
    if len(timestamps) <= EVENT_DRAFT_TIMESTAMP_SAMPLE_LIMIT:
        return list(value), []
    keep = set(timestamps[:EVENT_DRAFT_TIMESTAMP_SAMPLE_HEAD] + timestamps[-EVENT_DRAFT_TIMESTAMP_SAMPLE_TAIL:])
    sampled = [item for item in value if str(item.get("timestamp") or "") in keep]
    note = f"事件时间戳 sample: {len(keep)}/{len(timestamps)}；保留前 {EVENT_DRAFT_TIMESTAMP_SAMPLE_HEAD} 个和后 {EVENT_DRAFT_TIMESTAMP_SAMPLE_TAIL} 个时间戳"
    return sampled, [note]


def sample_rows_by_event_time(rows: list[tuple[Any, ...]], *, time_index: int) -> tuple[list[tuple[Any, ...]], list[str]]:
    timestamps = list(dict.fromkeys(str(row[time_index]) for row in rows))
    if len(timestamps) <= EVENT_DRAFT_TIMESTAMP_SAMPLE_LIMIT:
        return rows, []
    keep = set(timestamps[:EVENT_DRAFT_TIMESTAMP_SAMPLE_HEAD] + timestamps[-EVENT_DRAFT_TIMESTAMP_SAMPLE_TAIL:])
    sampled = [row for row in rows if str(row[time_index]) in keep]
    note = f"事件时间戳 sample: {len(keep)}/{len(timestamps)}；保留前 {EVENT_DRAFT_TIMESTAMP_SAMPLE_HEAD} 个和后 {EVENT_DRAFT_TIMESTAMP_SAMPLE_TAIL} 个时间戳"
    return sampled, [note]


def lifecycle_notice_table_lines(
    value: Sequence[Mapping[str, Any]],
    *,
    table_lines: TableLines,
    table_cell_is_complex: TableCellIsComplex,
    notice_scalar: Callable[[Any], str],
    indent: str = "",
    highlight_cell: HighlightCell | None = None,
    highlight_rows: bool = False,
) -> list[str] | None:
    extra_columns: list[str] = []
    preferred_extra_columns = [
        "lifecycle_source_type",
        "lifecycle_source",
        "lifecycle_source_function",
        "lifecycle_source_query_date",
        "lifecycle_fetched_at",
        "lifecycle_exchange",
        "open_date",
        "expire_date",
        "notice_date",
    ]
    ignored = {
        "product",
        "contract",
        "uid",
        "contract_product",
        "contract_object",
        "notice_type",
        "notice_reason",
        "last_trade_date",
        "delivery_date",
    }
    for item in value:
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        for key, item_value in payload.items():
            key_text = str(key)
            if key_text in ignored or table_cell_is_complex(item_value):
                continue
            if key_text not in extra_columns:
                extra_columns.append(key_text)
    extra_columns = [
        key for key in preferred_extra_columns if key in extra_columns
    ] + [
        key for key in extra_columns if key not in preferred_extra_columns
    ]
    grouped_rows: dict[tuple[Any, ...], dict[str, Any]] = {}
    for item in value:
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        notice_type = payload.get("notice_type")
        if notice_type not in {"force_close", "rollover"}:
            return None
        row_key = (
            item.get("timestamp") or "",
            payload.get("product") or "",
            notice_scalar(payload.get("contract_product") or payload.get("contract") or payload.get("uid") or payload.get("contract_object")),
            notice_type,
            payload.get("notice_reason") or "",
            notice_scalar(payload.get("last_trade_date")),
            notice_scalar(payload.get("delivery_date")),
            *[notice_scalar(payload.get(column)) for column in extra_columns],
        )
        grouped = grouped_rows.setdefault(row_key, {"strategies": []})
        strategy = item.get("strategy")
        if strategy not in (None, ""):
            grouped["strategies"].append(str(strategy))
    rows = []
    for row_key, grouped in grouped_rows.items():
        strategies = ", ".join(sorted(dict.fromkeys(grouped.get("strategies") or [])))
        row = tuple([row_key[0], strategies, *row_key[1:]])
        rows.append(highlight_row(row, highlight_cell=highlight_cell) if highlight_rows else row)
    if not rows:
        return None
    return table_lines(
        ("notice_time", "strategy", "product", "contract", "notice_type", "reason", "last_trade_date", "delivery_date", *extra_columns),
        rows,
        indent=indent,
    )


def notice_scalar(value: Any, *, audit_text: AuditText) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    if str(value).strip().lower() in {"nan", "nat", "none"}:
        return ""
    if isinstance(value, Mapping):
        for key in ("name", "repr", "value", "contract_product", "contract", "uid"):
            item = value.get(key)
            if item not in (None, ""):
                return str(item)
        return audit_text(value).replace("\n", " ")
    return str(value)


def event_payload_details(payload: Any) -> Any:
    if not isinstance(payload, Mapping):
        return payload
    ignored = {"kind", "ledger_id", "trading_day", "notice_type", "notice_reason", "reason", "product"}
    return {key: value for key, value in payload.items() if key not in ignored}


def event_payload_table_text(value: Any, *, table_lines: TableLines) -> str | None:
    if not isinstance(value, list) or not value:
        return None
    if not all(isinstance(item, dict) for item in value):
        return None
    if not all(looks_like_event_payload(item) for item in value):
        return None
    rows = []
    for payload in value:
        details = event_payload_details(payload)
        rows.append((
            payload.get("kind") or "",
            payload.get("product") or payload.get("ledger_id") or payload.get("trading_day") or "",
            payload.get("notice_type") or payload.get("kind") or "",
            payload.get("notice_reason") or payload.get("reason") or "",
            details if details else "",
        ))
    return "\n".join(table_lines(("event", "subject", "action", "reason", "details"), rows))


def looks_like_event_payload(value: Mapping[str, Any]) -> bool:
    if "kind" not in value:
        return False
    event_keys = {"ledger_id", "trading_day", "product", "notice_type", "notice_reason", "reason"}
    return any(key in value for key in event_keys) or len(value) == 1


def trading_day_resolver_text(
    value: Mapping[str, Any],
    *,
    select_sample_part: SelectSamplePart,
    sample_note_lines: Callable[[dict[str, Any], str], list[str]],
    single_sample_frame: Callable[[dict[str, Any]], tuple[dict[str, Any], list[str]]],
    dataframe_table_lines: Callable[..., list[str]],
) -> str:
    lines = ["TimestampTradingDayResolver: timestamp -> trading_day（仅用于交易日级历史字段记录）"]
    effective_rule = value.get("effective_rule")
    if effective_rule:
        lines.append(f"effective_rule = {effective_rule}")
    mapping_count = value.get("mapping_count")
    if mapping_count is not None:
        lines.append(f"mapping_count = {mapping_count}")
    timestamp_index = value.get("timestamp_index")
    if isinstance(timestamp_index, dict) and {"start", "end"} <= set(timestamp_index):
        lines.append(f"timestamp_index = {timestamp_index.get('start')} → {timestamp_index.get('end')}")
    trading_days = value.get("trading_days")
    if isinstance(trading_days, dict):
        count = trading_days.get("count")
        start = trading_days.get("start")
        end = trading_days.get("end")
        if count is not None:
            lines.append(f"trading_days = {count} days; {start} → {end}")
    sample = value.get("sample")
    if isinstance(sample, dict):
        selected = select_sample_part(sample, lambda part: isinstance(part, dict))
        if selected is not None:
            lines.extend(sample_note_lines(sample, selected.name))
            part, row_notes = single_sample_frame(selected.value)
            lines.extend(row_notes)
            lines.append(f"sample.{selected.name}:")
            lines.extend(dataframe_table_lines(part, indent="  "))
    return "\n".join(lines)
