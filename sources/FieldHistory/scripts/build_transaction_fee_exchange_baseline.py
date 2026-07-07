"""Build exchange TransactionFee baseline events from a fee-unit map.

The user-facing fee table classifies each product as either:

- ``money``: fee by traded notional ratio, stored in ``*RatioByMoney``.
- ``volume``: fixed fee per lot, stored in ``*RatioByVolume``.

OpenCTP latest snapshots may contain broker add-ons in the complementary unit
column. This builder therefore treats OpenCTP as cross-check evidence only: it
never copies both units into exchange baseline rows. The non-applicable unit is
always written as zero.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.data.field_history import load_openctp_latest_market_rule_frame


FEE_LEGS = (
    ("OpenRatioByMoney", "OpenRatioByVolume", "开仓"),
    ("CloseRatioByMoney", "CloseRatioByVolume", "平昨"),
    ("CloseTodayRatioByMoney", "CloseTodayRatioByVolume", "平今"),
)
BROKER_ADDON_BY_UNIT = {
    "money": 0.0000008,
    "volume": 0.01,
}

DEFAULT_MAP = (
    Path(__file__).resolve().parents[1]
    / "events"
    / "TransactionFee"
    / "exchange_fee_baseline_units_20260707.json"
)
DEFAULT_OUTPUT = (
    Path(__file__).resolve().parents[1]
    / "events"
    / "TransactionFee"
    / "exchange_fee_baseline_20260707.jsonl"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", default=str(DEFAULT_MAP), help="Fee-unit baseline JSON map")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output JSONL event file")
    parser.add_argument("--audit-output", default="", help="Optional CSV cross-check report")
    args = parser.parse_args(argv)

    mapping = _load_mapping(Path(args.map))
    events, audit = build_events(mapping)
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    if args.audit_output:
        audit_path = Path(args.audit_output).expanduser().resolve()
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(audit).to_csv(audit_path, index=False)
    print(json.dumps({
        "events": len(events),
        "products": len(mapping["products"]),
        "output": str(output),
        "audit_rows": len(audit),
    }, ensure_ascii=False, indent=2))
    return 0


def build_events(mapping: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    products = list(mapping["products"])
    baseline_day = str(mapping.get("baseline_effective_trading_day") or "1900-01-02")
    accessed_at = str(mapping.get("source_accessed_at") or "")
    official_urls = dict(mapping.get("official_source_urls") or {})
    secondary_urls = dict(mapping.get("secondary_source_urls") or {})
    openctp = _latest_product_fee_frame()
    events: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    for product in products:
        instrument = str(product["instrument"]).upper()
        exchange = str(product["exchange"]).upper()
        unit = str(product["unit"]).lower()
        if unit not in {"money", "volume"}:
            raise ValueError(f"unsupported unit for {instrument}: {unit!r}")
        baseline_value = _parse_fee_value(product["value"], unit=unit)
        openctp_values = _openctp_values_for_instrument(openctp, instrument)
        source_url = official_urls.get(exchange) or secondary_urls.get("Sina") or ""
        for money_field, volume_field, leg_label in FEE_LEGS:
            active_field = money_field if unit == "money" else volume_field
            active_value, active_source = _baseline_for_leg(
                unit=unit,
                table_value=baseline_value,
                openctp_value=openctp_values.get(active_field),
                leg_label=leg_label,
            )
            money_value = active_value if unit == "money" else 0.0
            volume_value = active_value if unit == "volume" else 0.0
            for field_name, value in ((money_field, money_value), (volume_field, volume_value)):
                events.append(_event(
                    exchange=exchange,
                    instrument=instrument,
                    label=str(product.get("label") or ""),
                    field_name=field_name,
                    value=value,
                    source_url=source_url,
                    accessed_at=accessed_at,
                    effective_day=baseline_day,
                    raw_note=(
                        f"{instrument} exchange baseline transaction fee from user fee-unit table: "
                        f"{product['value']} by {unit}; {leg_label} uses {field_name}; "
                        f"active leg source={active_source}."
                    ),
                    parser_notes=(
                        "Baseline unit chosen from user-supplied table and cross-checked against OpenCTP latest; "
                        "complementary unit is forced to zero so broker add-ons do not enter exchange source."
                    ),
                ))
            audit.append(_audit_row(
                instrument=instrument,
                exchange=exchange,
                unit=unit,
                leg=leg_label,
                active_source=active_source,
                baseline_money=money_value,
                baseline_volume=volume_value,
                openctp_money=openctp_values.get(money_field),
                openctp_volume=openctp_values.get(volume_field),
            ))
    return events, audit


def _load_mapping(path: Path) -> dict[str, Any]:
    with path.expanduser().resolve().open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or not isinstance(data.get("products"), list):
        raise ValueError("baseline map must contain a products list")
    return data


def _latest_product_fee_frame() -> pd.DataFrame:
    frame = load_openctp_latest_market_rule_frame(store_key="openctp")
    if frame.empty:
        return pd.DataFrame()
    product_rows = frame[frame["contract_codes"].map(lambda value: str(value).strip() in {"[]", ""})].copy()
    fee_fields = {field for pair in FEE_LEGS for field in pair[:2]}
    product_rows = product_rows[product_rows["field_name"].isin(fee_fields)].copy()
    product_rows["value_num"] = pd.to_numeric(product_rows["value"], errors="coerce")
    return product_rows


def _openctp_values_for_instrument(frame: pd.DataFrame, instrument: str) -> dict[str, float | None]:
    if frame.empty:
        return {}
    rows = frame[frame["instrument"].astype(str).str.upper() == instrument]
    result: dict[str, float | None] = {}
    for field_name, group in rows.groupby("field_name"):
        values = group["value_num"].dropna()
        result[str(field_name)] = float(values.iloc[-1]) if not values.empty else None
    return result


def _parse_fee_value(value: Any, *, unit: str) -> float:
    text = str(value).strip()
    if text.endswith("%"):
        if unit != "money":
            raise ValueError(f"percent fee {value!r} must use money unit")
        return float(text[:-1]) / 100.0
    if unit != "volume":
        raise ValueError(f"fixed fee {value!r} must use volume unit")
    return float(text)


def _baseline_for_leg(*, unit: str, table_value: float, openctp_value: float | None, leg_label: str) -> tuple[float, str]:
    if openctp_value is None:
        return table_value, "table"
    addon = BROKER_ADDON_BY_UNIT[unit]
    if abs(openctp_value - table_value) <= addon + 1e-12:
        return table_value, "table"
    if openctp_value == 0:
        return 0.0, "openctp-stripped"
    stripped = openctp_value - addon
    if stripped < 0:
        return openctp_value, "openctp"
    if abs(stripped) < 1e-12:
        return 0.0, "openctp-stripped"
    return stripped, "openctp-stripped"


def _event(
    *,
    exchange: str,
    instrument: str,
    label: str,
    field_name: str,
    value: float,
    source_url: str,
    accessed_at: str,
    effective_day: str,
    raw_note: str,
    parser_notes: str,
) -> dict[str, Any]:
    event_key = f"{exchange}|{instrument}|{field_name}|{effective_day}|{value}"
    event_id = "transaction_fee_baseline_" + hashlib.sha1(event_key.encode("utf-8")).hexdigest()[:24]
    return {
        "agent_name": "codex",
        "contract_codes": [],
        "data_source": exchange,
        "effective_timestamp": "",
        "effective_trading_day": effective_day,
        "event_id": event_id,
        "evidence_text": raw_note,
        "field_group": "TransactionFee",
        "field_name": field_name,
        "instrument": instrument,
        "instrument_label": label,
        "instrument_type": "future",
        "parser_notes": parser_notes,
        "raw_note": raw_note,
        "source_accessed_at": accessed_at,
        "source_notice_id": "exchange-baseline-user-table-2026-07-07",
        "source_url": source_url,
        "value": value,
    }


def _audit_row(
    *,
    instrument: str,
    exchange: str,
    unit: str,
    leg: str,
    active_source: str,
    baseline_money: float,
    baseline_volume: float,
    openctp_money: float | None,
    openctp_volume: float | None,
) -> dict[str, Any]:
    active_baseline = baseline_money if unit == "money" else baseline_volume
    active_openctp = openctp_money if unit == "money" else openctp_volume
    inactive_openctp = openctp_volume if unit == "money" else openctp_money
    delta = None if active_openctp is None else float(active_openctp - active_baseline)
    return {
        "instrument": instrument,
        "exchange": exchange,
        "leg": leg,
        "unit": unit,
        "active_source": active_source,
        "baseline_money": baseline_money,
        "baseline_volume": baseline_volume,
        "openctp_money": openctp_money,
        "openctp_volume": openctp_volume,
        "active_unit_delta_openctp_minus_baseline": delta,
        "inactive_openctp_nonzero": bool(inactive_openctp not in (None, 0.0)),
    }


if __name__ == "__main__":
    raise SystemExit(main())
