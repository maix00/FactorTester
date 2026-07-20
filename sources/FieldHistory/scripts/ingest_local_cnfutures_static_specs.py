"""Build LocalCNFutures static-spec audit candidates.

LocalCNFutures product-catalog rows are local static metadata.  They can be used
to audit whether official exchange listing/specification events are complete,
but they must not be appended to ``agent_field_change_events`` or materialized
into ``historical_field_values``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from typing import Any

import pandas as pd

from sources.LocalCNFutures.product_catalog import load_product_catalog
from tools.data.field_history import _ensure_store_registered
from tools.data.hub import DataHub


BOUNDARY_DAY = pd.Timestamp("2024-01-02")
SOURCE_URL = "LocalCNFutures product catalog"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-key", default="openctp")
    parser.add_argument("--output-json", default="", help="Optional audit candidate JSON path.")
    args = parser.parse_args(argv)

    events = build_events(store_key=args.store_key)
    print(json.dumps({
        "candidate_events": len(events),
        "inserted": 0,
        "sample_event_ids": [event["event_id"] for event in events[:20]],
    }, ensure_ascii=False, indent=2))
    if args.output_json:
        from pathlib import Path

        output = Path(args.output_json).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote LocalCNFutures audit candidates: {output}")
    return 0


def build_events(*, store_key: str = "openctp") -> list[dict[str, Any]]:
    hub = DataHub.get_instance()
    _ensure_store_registered(hub, store_key)
    catalog = load_product_catalog(sync=False)
    accessed_at = datetime.now().astimezone().isoformat(timespec="seconds")
    events: list[dict[str, Any]] = []
    for row in catalog.to_dict("records"):
        exchange = str(row.get("交易所代码") or "").strip().upper()
        instrument = str(row.get("品种代码") or "").strip().upper()
        label = str(row.get("合约标的") or instrument).strip()
        if not exchange or not instrument:
            continue
        listing_day = _parse_listing_day(row.get("标准合约上市日"))
        for field_name, raw_value in (
            ("VolumeMultiple", row.get("合约乘数")),
            ("PriceTick", row.get("最小跳动")),
        ):
            value = _parse_float(raw_value)
            if value is None or value <= 0:
                continue
            event = _event(
                exchange=exchange,
                instrument=instrument,
                label=label,
                field_name=field_name,
                value=value,
                listing_day=listing_day,
                accessed_at=accessed_at,
            )
            events.append(event)
    return _dedupe_events(events)


def _event(
    *,
    exchange: str,
    instrument: str,
    label: str,
    field_name: str,
    value: float,
    listing_day: pd.Timestamp | None,
    accessed_at: str,
) -> dict[str, Any]:
    if listing_day is not None and listing_day > BOUNDARY_DAY:
        effective_day = listing_day
        change_type = "baseline"
        source_notice_id = f"LocalCNFutures-product-catalog-{instrument}-listing-static-spec"
        note = "Product listed after 2024 boundary; local catalog static spec used as listing baseline pending exchange notice backfill."
    else:
        effective_day = BOUNDARY_DAY
        change_type = "asof_confirmed"
        source_notice_id = f"LocalCNFutures-product-catalog-20240102-static-spec-asof"
        note = "Product already listed at 2024 boundary; local catalog static spec used as phase-1 as-of confirmation pending exchange notice backfill."
    event_id = "field_history_static_spec_" + hashlib.sha1(
        f"{exchange}:{instrument}:{field_name}:{effective_day.date()}:{value}:{change_type}".encode("utf-8")
    ).hexdigest()[:24]
    return {
        "event_id": event_id,
        "data_source": "LocalCNFutures",
        "field_group": "TradingRules",
        "source_url": SOURCE_URL,
        "source_accessed_at": accessed_at,
        "agent_name": "Agent:LocalCNFutures",
        "requester_key": "field-history-local-cnfutures-static-specs",
        "instrument": instrument,
        "instrument_label": label,
        "instrument_type": "future",
        "scope_type": "product",
        "exchange": exchange,
        "field_name": field_name,
        "effective_trading_day": effective_day.strftime("%Y-%m-%d"),
        "effective_timestamp": f"{effective_day.strftime('%Y-%m-%d')} 09:00:00",
        "value": float(value),
        "contract_codes": [],
        "contract_scope_type": "all",
        "change_type": change_type,
        "source_notice_id": source_notice_id,
        "raw_note": f"AUDIT ONLY: {note}",
        "evidence_text": "LocalCNFutures product catalog columns: 合约乘数, 最小跳动, 标准合约上市日.",
        "parser_notes": (
            "Audit candidate only. Do not ingest LocalCNFutures product-catalog rows as FieldHistory truth; "
            "find the official exchange listing notice, product specification, or business rule."
        ),
    }


def _parse_listing_day(value: Any) -> pd.Timestamp | None:
    text = str(value or "").strip()
    if not text:
        return None
    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).normalize()


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _dedupe_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for event in events:
        event_id = str(event["event_id"])
        prior = by_id.get(event_id)
        if prior is not None and prior != event:
            # The product catalog may contain historical product versions with
            # the same product code and unchanged static spec.  Keep the later
            # row deterministically only when the value payload is identical.
            comparable = {
                key: event.get(key)
                for key in ("instrument", "field_name", "effective_trading_day", "value", "change_type")
            }
            prior_comparable = {
                key: prior.get(key)
                for key in ("instrument", "field_name", "effective_trading_day", "value", "change_type")
            }
            if comparable != prior_comparable:
                raise ValueError(f"conflicting static spec event_id={event_id}")
        by_id[event_id] = event
    return list(by_id.values())


if __name__ == "__main__":
    raise SystemExit(main())
