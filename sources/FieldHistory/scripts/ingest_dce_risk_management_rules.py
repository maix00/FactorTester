"""Expand DCE lifecycle trading-rule overlays into FieldHistory value rows.

The DCE Risk Management Measures define dynamic margin/price-limit overlays
such as delivery-month margin and single-sided limit-move escalation.  The
replay path must not interpret those rules at runtime; this script materializes
the deterministic contract-calendar parts into ordinary FieldHistory value rows
with ``change_type=rule`` so FieldHistory can provide resolved numeric values.

Only deterministic contract-calendar rules are expanded here.  Single-sided
limit-move escalation depends on market path state and is intentionally not
represented as a static historical field value.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from sources.FieldHistory.scripts.ingest_field_history_events import _rebuild_view
from sources.LocalCNFutures import SOURCE_DATA_DIR
from tools.data.field_history import (
    HISTORICAL_FIELD_TABLE,
    HistoricalFieldLookupError,
    _ensure_store_registered,
    load_market_rule_field_provider,
)
from tools.data.field_history_agent_ingest import (
    AGENT_EVENT_TABLE,
    append_agent_field_change_events,
    ensure_agent_event_schema,
    materialize_agent_events_to_history,
)
from tools.data.hub import DataHub


SOURCE_NOTICE_ID = "DCE-risk-management-measures-delivery-calendar-rules"
SOURCE = {
    "data_source": "DCE",
    "source_url": "http://www.dce.com.cn/dalianshangpin/fgfz/6142914/6142922/6262956/index.html",
    "source_accessed_at": "2026-07-09T00:00:00+08:00",
    "source_notice_id": SOURCE_NOTICE_ID,
    "raw_note": (
        "大连商品交易所风险管理办法规定：期货合约交易过程中的交易保证金标准按照不同阶段定期调整。"
        "除聚乙烯、聚丙烯和聚氯乙烯外，交割月份前一个月第十五个交易日起为10%，"
        "交割月份第一个交易日起为20%；聚乙烯、聚丙烯和聚氯乙烯进入交割月份第一个交易日起为20%。"
        "同一合约同时适用多个保证金标准时按数值大的执行。交割月份涨跌停板幅度为6%。"
    ),
    "parser_notes": (
        "Expanded from official DCE Risk Management Measures into contract-scoped numeric FieldHistory rows. "
        "Effective timestamp is the previous DCE trading day's 15:00 settlement boundary because the rule "
        "states stage margins execute from settlement before the stage starts. Values are pre-combined with "
        "the latest prior product-level base value using max where the rule says the larger margin applies. "
        "Path-dependent single-sided limit-move escalation is not expanded here."
    ),
}


_SPECIAL_DELIVERY_PRODUCTS = {"L", "PP", "V"}
_FIELDS_BY_STAGE = {
    "margin_long": "LongMarginRatioByMoney",
    "margin_short": "ShortMarginRatioByMoney",
    "limit": "LimitUpDownRatio",
}


@dataclass(frozen=True, slots=True)
class ContractWindow:
    product: str
    contract_code: str
    delivery_year: int
    delivery_month: int
    first_delivery_month_trading_day: pd.Timestamp | None
    fifteenth_trading_day_before_delivery_month: pd.Timestamp | None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-key", default="openctp")
    parser.add_argument("--start-date", default="2024-01-01")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    events = build_events(store_key=args.store_key, start_date=args.start_date)
    print(json.dumps({
        "candidate_events": len(events),
        "inserted": 0 if args.dry_run else len(events),
        "sample_event_ids": [event["event_id"] for event in events[:20]],
    }, ensure_ascii=False, indent=2))
    if args.dry_run:
        return 0

    _replace_existing_rule_events(store_key=args.store_key)
    if events:
        append_agent_field_change_events(events, store_key=args.store_key)
    for field_group in {"Margin", "TradingRules"}:
        materialize_agent_events_to_history(store_key=args.store_key, data_source="DCE", field_group=field_group)
        _rebuild_view(field_group, store_key=args.store_key)
    return 0


def build_events(*, store_key: str = "openctp", start_date: str = "2024-01-01") -> list[dict[str, Any]]:
    dayk = _load_dce_dayk()
    start_day = pd.Timestamp(start_date).normalize()
    provider = load_market_rule_field_provider(
        store_key=store_key,
        include_openctp_latest=False,
        transaction_fee_source="exchange",
    )
    dce_trading_days = _dce_trading_days(dayk)
    windows = _contract_windows(dayk, start_day=start_day, dce_trading_days=dce_trading_days)
    events: list[dict[str, Any]] = []
    for window in windows:
        events.extend(_events_for_window(window, provider=provider, trading_days=dce_trading_days))
    return _dedupe_events(events)


def _load_dce_dayk() -> pd.DataFrame:
    path = Path(SOURCE_DATA_DIR) / "data_dayk.parquet"
    frame = pd.read_parquet(
        path,
        columns=["trading_day", "exchange_id", "product_id", "unique_instrument_id"],
    )
    frame = frame[frame["exchange_id"].astype(str).str.upper() == "DCE"].copy()
    frame["trading_day"] = pd.to_datetime(frame["trading_day"], errors="coerce").dt.normalize()
    frame = frame.dropna(subset=["trading_day", "product_id", "unique_instrument_id"])
    return frame


def _dce_trading_days(dayk: pd.DataFrame) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(sorted(pd.to_datetime(dayk["trading_day"].dropna().unique()))).tz_localize(None)


def _contract_windows(
    dayk: pd.DataFrame,
    *,
    start_day: pd.Timestamp,
    dce_trading_days: pd.DatetimeIndex,
) -> list[ContractWindow]:
    contracts = dayk[["product_id", "unique_instrument_id"]].drop_duplicates()
    windows: list[ContractWindow] = []
    for row in contracts.itertuples(index=False):
        product = str(row.product_id).upper()
        contract_code = _contract_code_from_uid(str(row.unique_instrument_id))
        delivery = _delivery_month(contract_code)
        if delivery is None:
            continue
        year, month = delivery
        if pd.Timestamp(year=year, month=month, day=1) < start_day - pd.offsets.MonthBegin(1):
            continue
        delivery_days = _days_in_month(dce_trading_days, year=year, month=month)
        prior_month = pd.Timestamp(year=year, month=month, day=1) - pd.offsets.MonthBegin(1)
        prior_days = _days_in_month(dce_trading_days, year=int(prior_month.year), month=int(prior_month.month))
        windows.append(ContractWindow(
            product=product,
            contract_code=contract_code,
            delivery_year=year,
            delivery_month=month,
            first_delivery_month_trading_day=delivery_days[0] if len(delivery_days) else None,
            fifteenth_trading_day_before_delivery_month=prior_days[14] if len(prior_days) >= 15 else None,
        ))
    return sorted(windows, key=lambda item: (item.product, item.contract_code))


def _events_for_window(
    window: ContractWindow,
    *,
    provider,
    trading_days: pd.DatetimeIndex,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    product_family = window.product.removesuffix("_F")
    if product_family not in _SPECIAL_DELIVERY_PRODUCTS and window.fifteenth_trading_day_before_delivery_month is not None:
        for field_name in (_FIELDS_BY_STAGE["margin_long"], _FIELDS_BY_STAGE["margin_short"]):
            events.append(_numeric_rule_event(
                window,
                field_name,
                _combined_value(provider, window.product, field_name, window.fifteenth_trading_day_before_delivery_month, 0.10),
                window.fifteenth_trading_day_before_delivery_month,
                trading_days=trading_days,
                stage="delivery_previous_month_15th_trading_day_margin",
                rule_value=0.10,
            ))
    if window.first_delivery_month_trading_day is not None:
        for field_name in (_FIELDS_BY_STAGE["margin_long"], _FIELDS_BY_STAGE["margin_short"]):
            events.append(_numeric_rule_event(
                window,
                field_name,
                _combined_value(provider, window.product, field_name, window.first_delivery_month_trading_day, 0.20),
                window.first_delivery_month_trading_day,
                trading_days=trading_days,
                stage="delivery_month_first_trading_day_margin",
                rule_value=0.20,
            ))
        events.append(_numeric_rule_event(
            window,
            _FIELDS_BY_STAGE["limit"],
            0.06,
            window.first_delivery_month_trading_day,
            trading_days=trading_days,
            stage="delivery_month_price_limit",
            rule_value=0.06,
        ))
    return events


def _combined_value(provider, product: str, field_name: str, day: pd.Timestamp, rule_value: float) -> float:
    if field_name == _FIELDS_BY_STAGE["limit"]:
        return rule_value
    try:
        base = provider.resolve_by_trading_day(
            f"{product}.DCE",
            field_name,
            day,
            instrument_type="future",
            fallback="latest_available",
        ).value
        return max(float(base or 0.0), float(rule_value))
    except (HistoricalFieldLookupError, ValueError, TypeError):
        return float(rule_value)


def _numeric_rule_event(
    window: ContractWindow,
    field_name: str,
    value: float,
    effective_day: pd.Timestamp,
    *,
    trading_days: pd.DatetimeIndex,
    stage: str,
    rule_value: float,
) -> dict[str, Any]:
    effective_trading_day = effective_day.strftime("%Y-%m-%d")
    effective_timestamp = _previous_settlement_timestamp(effective_day, trading_days)
    event_id = "field_history_rule_value_" + hashlib.sha1(
        f"{SOURCE_NOTICE_ID}:{window.product}:{window.contract_code}:{field_name}:{effective_trading_day}:{stage}".encode("utf-8")
    ).hexdigest()[:24]
    return {
        "event_id": event_id,
        "data_source": SOURCE["data_source"],
        "field_group": "Margin" if field_name in {"LongMarginRatioByMoney", "ShortMarginRatioByMoney"} else "TradingRules",
        "source_url": SOURCE["source_url"],
        "source_accessed_at": SOURCE["source_accessed_at"],
        "agent_name": "Agent:DCE",
        "requester_key": "field-history-official-dce-risk-rules",
        "instrument": window.product,
        "instrument_label": window.product,
        "instrument_type": "future",
        "scope_type": "product",
        "exchange": "DCE",
        "field_name": field_name,
        "effective_trading_day": effective_trading_day,
        "effective_timestamp": effective_timestamp,
        "value": float(value),
        "contract_codes": [window.contract_code],
        "contract_scope_type": "explicit",
        "change_type": "rule",
        "source_notice_id": SOURCE_NOTICE_ID,
        "raw_note": SOURCE["raw_note"],
        "evidence_text": SOURCE["raw_note"],
        "parser_notes": (
            f"{SOURCE['parser_notes']} stage={stage}; rule_value={rule_value}; "
            f"delivery_month={window.delivery_year:04d}-{window.delivery_month:02d}; "
            f"contract={window.product}{window.contract_code}.DCE."
        ),
    }


def _previous_settlement_timestamp(day: pd.Timestamp, trading_days: pd.DatetimeIndex) -> str:
    position = trading_days.searchsorted(day, side="left") - 1
    if position >= 0:
        prev = pd.Timestamp(trading_days[position])
        return f"{prev.strftime('%Y-%m-%d')} 15:00:00"
    return f"{pd.Timestamp(day).strftime('%Y-%m-%d')} 09:00:00"


def _contract_code_from_uid(uid: str) -> str:
    parts = str(uid).split("|")
    return parts[3].upper() if len(parts) >= 4 else ""


def _delivery_month(contract_code: str) -> tuple[int, int] | None:
    digits = "".join(char for char in str(contract_code).upper() if char.isdigit())
    if len(digits) < 4:
        return None
    yy = int(digits[:2])
    month = int(digits[2:4])
    if not 1 <= month <= 12:
        return None
    return 2000 + yy, month


def _days_in_month(days: pd.DatetimeIndex, *, year: int, month: int) -> pd.DatetimeIndex:
    return pd.DatetimeIndex([day for day in days if day.year == year and day.month == month])


def _dedupe_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for event in events:
        prior = by_id.get(str(event["event_id"]))
        if prior is not None and prior != event:
            raise ValueError(f"conflicting DCE rule event_id={event['event_id']}")
        by_id[str(event["event_id"])] = event
    return list(by_id.values())


def _replace_existing_rule_events(*, store_key: str) -> None:
    hub = DataHub.get_instance()
    _ensure_store_registered(hub, store_key)
    with hub.connect_store(store_key) as conn:
        ensure_agent_event_schema(conn)
        event_ids = [
            str(row[0])
            for row in conn.execute(
                f"""
                SELECT event_id
                FROM {AGENT_EVENT_TABLE}
                WHERE data_source = 'DCE'
                  AND source_notice_id = ?
                  AND change_type = 'rule'
                """,
                (SOURCE_NOTICE_ID,),
            ).fetchall()
        ]
        legacy_ids = [
            str(row[0])
            for row in conn.execute(
                f"""
                SELECT event_id
                FROM {AGENT_EVENT_TABLE}
                WHERE data_source = 'DCE'
                  AND event_id LIKE 'field_history_rule_%'
                  AND change_type = 'rule'
                """
            ).fetchall()
        ]
        all_ids = sorted(set(event_ids + legacy_ids))
        if not all_ids:
            return
        conn.executemany(
            f"DELETE FROM {AGENT_EVENT_TABLE} WHERE event_id = ?",
            [(event_id,) for event_id in all_ids],
        )
        source_keys = [(f"agent/DCE/{event_id}",) for event_id in all_ids]
        try:
            conn.executemany(
                f'DELETE FROM "{HISTORICAL_FIELD_TABLE}" WHERE source_key = ?',
                source_keys,
            )
        except sqlite3.OperationalError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
