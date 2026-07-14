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
) -> list[str]:
    lifecycle_notice_lines = lifecycle_notice_table_lines(
        value,
        table_lines=table_lines,
        table_cell_is_complex=table_cell_is_complex,
        notice_scalar=notice_scalar,
        indent=indent,
    )
    if lifecycle_notice_lines is not None:
        return lifecycle_notice_lines
    order_lines = order_event_draft_table_lines(value, table_lines=table_lines, indent=indent)
    if order_lines is not None:
        return order_lines
    rows = []
    for item in value:
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        details = event_payload_details(payload)
        route = item.get("strategy") or item.get("ledger") or ""
        rows.append((
            item.get("timestamp") or "",
            item.get("kind") or payload.get("kind") or "",
            route,
            payload.get("product") or payload.get("ledger_id") or payload.get("trading_day") or "",
            payload.get("notice_type") or payload.get("kind") or "",
            payload.get("notice_reason") or payload.get("reason") or "",
            details if details else "",
        ))
    return table_lines(
        ("timestamp", "event", "route", "subject", "action", "reason", "details"),
        rows,
        indent=indent,
    )


def order_event_draft_table_lines(
    value: Sequence[Mapping[str, Any]],
    *,
    table_lines: TableLines,
    indent: str = "",
) -> list[str] | None:
    rows = []
    for item in value:
        payload = item.get("payload") if isinstance(item.get("payload"), Mapping) else {}
        if str(item.get("kind") or payload.get("kind") or "").lower() != "order":
            return None
        if not looks_like_order_payload(payload):
            return None
        rows.append((
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
        ))
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


def lifecycle_notice_table_lines(
    value: Sequence[Mapping[str, Any]],
    *,
    table_lines: TableLines,
    table_cell_is_complex: TableCellIsComplex,
    notice_scalar: Callable[[Any], str],
    indent: str = "",
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
        rows.append(tuple([row_key[0], strategies, *row_key[1:]]))
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
