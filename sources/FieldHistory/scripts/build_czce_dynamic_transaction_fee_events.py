"""Build CZCE dynamic TransactionFee notice events.

Some CZCE fee notices do not name a fixed product-level or explicit contract
list.  For example Zhengshanghan [2020] 481 applies to non-1/5/9 contracts
from the first trading day five months before the delivery month.  This script
materializes those notice rules into explicit contract events by using official
settlement-parameter snapshots only to discover listed contract codes and the
nearest available trading day calendar.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any


FEE_FIELDS = {
    "OpenRatioByMoney",
    "OpenRatioByVolume",
    "CloseRatioByMoney",
    "CloseRatioByVolume",
    "CloseTodayRatioByMoney",
    "CloseTodayRatioByVolume",
}

DEFAULT_SNAPSHOT_FILE = (
    Path("sources")
    / "FieldHistory"
    / "events"
    / "TransactionFee"
    / "exchange_settlement_changes_20180102_20260707.jsonl"
)
DEFAULT_OUTPUT_FILE = (
    Path("sources")
    / "FieldHistory"
    / "events"
    / "TransactionFee"
    / "czce_dynamic_notice_events.jsonl"
)


@dataclass(frozen=True)
class DynamicFeeRule:
    notice_id: str
    source_url: str
    source_accessed_at: str
    effective_trading_day: str
    effective_timestamp: str
    instruments: dict[str, tuple[str, float, float]]
    excluded_delivery_months: frozenset[int]
    months_before_delivery: int
    evidence_text: str
    parser_notes: str


RULE_2020_481 = DynamicFeeRule(
    notice_id="郑商函〔2020〕481号",
    source_url="https://www.gtjaqh.com/pc/a/b457cca6f911e42a9ca50b08e2587fe4",
    source_accessed_at="2026-07-08T00:00:00+08:00",
    # The notice says "2021-01-18 night session"; for CZCE night trading this
    # belongs to the next trading day.
    effective_trading_day="2021-01-19",
    effective_timestamp="2021-01-18 21:00:00",
    instruments={
        "CF": ("棉花", 2.0, 0.0),
        "SR": ("白糖", 1.5, 0.0),
        "OI": ("菜籽油", 1.0, 0.0),
        "RM": ("菜籽粕", 1.0, 0.0),
        "TA": ("PTA", 1.5, 0.0),
        "ZC": ("动力煤", 2.0, 0.0),
        "MA": ("甲醇", 2.0, 2.0),
        "FG": ("玻璃", 1.5, 1.5),
        "SM": ("锰硅", 1.5, 0.0),
        "SF": ("硅铁", 1.5, 0.0),
    },
    excluded_delivery_months=frozenset({1, 5, 9}),
    months_before_delivery=5,
    evidence_text=(
        "郑商函〔2020〕481号：2021年1月18日夜盘交易时起，对棉花等10个期货品种的"
        "非1、5、9合约，从进入交割月前5个月的第一个交易日起，手续费标准调整；"
        "表格列示交易手续费和平今仓手续费。"
    ),
    parser_notes=(
        "Dynamic CZCE notice rule. Settlement snapshots are used only to discover contract codes "
        "and available trading days; the fee values and scope semantics come from the notice text."
    ),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-file", default=str(DEFAULT_SNAPSHOT_FILE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_FILE))
    args = parser.parse_args(argv)

    snapshots = _load_czce_fee_snapshots(Path(args.snapshot_file))
    events = build_events(snapshots, rules=[RULE_2020_481])
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps({"output": str(output), "events": len(events)}, ensure_ascii=False, indent=2))
    return 0


def build_events(snapshots: list[dict[str, Any]], *, rules: list[DynamicFeeRule]) -> list[dict[str, Any]]:
    events: dict[str, dict[str, Any]] = {}
    trading_days = sorted({str(row["effective_trading_day"]) for row in snapshots})
    for rule in rules:
        for instrument, contract_code in _matching_contracts(snapshots, rule):
            scheduled_day = _scheduled_effective_day(contract_code, rule=rule, trading_days=trading_days)
            label, open_close_fee, close_today_fee = rule.instruments[instrument]
            for field_name, value in _fee_field_values(open_close_fee, close_today_fee).items():
                event = _event(
                    rule=rule,
                    instrument=instrument,
                    instrument_label=label,
                    contract_code=contract_code,
                    effective_trading_day=scheduled_day,
                    field_name=field_name,
                    value=value,
                )
                events[event["event_id"]] = event
    return [events[key] for key in sorted(events)]


def _load_czce_fee_snapshots(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            row = json.loads(text)
            if row.get("data_source") == "CZCE" and row.get("field_name") in FEE_FIELDS:
                rows.append(row)
    return rows


def _matching_contracts(snapshots: list[dict[str, Any]], rule: DynamicFeeRule) -> list[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for row in snapshots:
        instrument = str(row.get("instrument") or "").upper()
        if instrument not in rule.instruments:
            continue
        for contract_code in row.get("contract_codes") or []:
            code = str(contract_code).strip().upper()
            if not code:
                continue
            month = _contract_month(code)
            if month is None or month in rule.excluded_delivery_months:
                continue
            pairs.add((instrument, code))
    return sorted(pairs, key=lambda item: (item[0], _contract_sort_key(item[1])))


def _scheduled_effective_day(contract_code: str, *, rule: DynamicFeeRule, trading_days: list[str]) -> str:
    contract_month = _contract_year_month(contract_code)
    if contract_month is None:
        return rule.effective_trading_day
    trigger_month = _add_months(contract_month, -rule.months_before_delivery)
    first_available = _first_trading_day_in_month(trigger_month, trading_days)
    if first_available is None:
        first_available = _first_weekday_in_month(trigger_month).isoformat()
    return max(rule.effective_trading_day, first_available)


def _fee_field_values(open_close_fee: float, close_today_fee: float) -> dict[str, float]:
    return {
        "OpenRatioByMoney": 0.0,
        "OpenRatioByVolume": open_close_fee,
        "CloseRatioByMoney": 0.0,
        "CloseRatioByVolume": open_close_fee,
        "CloseTodayRatioByMoney": 0.0,
        "CloseTodayRatioByVolume": close_today_fee,
    }


def _event(
    *,
    rule: DynamicFeeRule,
    instrument: str,
    instrument_label: str,
    contract_code: str,
    effective_trading_day: str,
    field_name: str,
    value: float,
) -> dict[str, Any]:
    event_id = "transaction_fee_notice_" + hashlib.sha1(
        "|".join([
            "CZCE",
            rule.notice_id,
            instrument,
            contract_code,
            effective_trading_day,
            field_name,
            str(value),
        ]).encode("utf-8")
    ).hexdigest()[:24]
    return {
        "agent_name": "codex",
        "change_type": "change",
        "contract_codes": [contract_code],
        "contract_scope_type": "explicit",
        "data_source": "CZCE",
        "effective_timestamp": "",
        "effective_trading_day": effective_trading_day,
        "event_id": event_id,
        "evidence_text": rule.evidence_text,
        "field_group": "TransactionFee",
        "field_name": field_name,
        "instrument": instrument,
        "instrument_label": instrument_label,
        "instrument_type": "future",
        "parser_notes": rule.parser_notes,
        "raw_note": rule.evidence_text,
        "source_accessed_at": rule.source_accessed_at,
        "source_notice_id": rule.notice_id,
        "source_url": rule.source_url,
        "value": value,
    }


def _first_trading_day_in_month(month: date, trading_days: list[str]) -> str | None:
    prefix = f"{month.year:04d}-{month.month:02d}-"
    for candidate in trading_days:
        if candidate.startswith(prefix):
            return candidate
    return None


def _first_weekday_in_month(month: date) -> date:
    current = month
    while current.weekday() >= 5:
        current += timedelta(days=1)
    return current


def _contract_year_month(contract_code: str) -> date | None:
    text = str(contract_code).strip().upper()
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) == 3:
        digits = f"2{digits}"
    if len(digits) != 4:
        return None
    year = 2000 + int(digits[:2])
    month = int(digits[2:])
    if not (1 <= month <= 12):
        return None
    return date(year, month, 1)


def _contract_month(contract_code: str) -> int | None:
    ym = _contract_year_month(contract_code)
    return None if ym is None else ym.month


def _add_months(day: date, months: int) -> date:
    month_index = day.year * 12 + (day.month - 1) + months
    return date(month_index // 12, month_index % 12 + 1, 1)


def _contract_sort_key(contract_code: str) -> tuple[int, str]:
    ym = _contract_year_month(contract_code)
    return (-1, contract_code) if ym is None else (ym.year * 100 + ym.month, contract_code)


if __name__ == "__main__":
    raise SystemExit(main())
