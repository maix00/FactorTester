"""Ingest DCE exchange-level trading-management rule values.

The DCE Trading Management Measures state that every futures-contract order has
minimum order quantity 1 lot, while maximum order quantity is defined by each
product business rule.  This is an exchange-level default, not a product-level
listing baseline, so it is stored with ``instrument='*'`` and ``exchange='DCE'``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from typing import Any

import requests

from sources.FieldHistory.scripts.ingest_field_history_events import _rebuild_view
from tools.data.field_history import _ensure_store_registered
from tools.data.field_history_agent_ingest import (
    append_agent_field_change_events,
    ensure_agent_event_schema,
    materialize_agent_events_to_history,
)
from tools.data.hub import DataHub


CSRC_BASE = "https://neris.csrc.gov.cn/falvfagui/"
LAW_NAME = "大连商品交易所交易管理办法"
SOURCE_NAME = "CSRC-rules-db"
BOUNDARY_DAY = "2024-01-02"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-key", default="openctp")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    _ensure_store_registered(DataHub.get_instance(), args.store_key)
    events = build_events(store_key=args.store_key)
    print(json.dumps({
        "candidate_events_after_dedupe": len(events),
        "sample_event_ids": [event["event_id"] for event in events[:20]],
    }, ensure_ascii=False, indent=2))
    if args.dry_run or not events:
        return 0
    append_agent_field_change_events(events, store_key=args.store_key)
    materialize_agent_events_to_history(store_key=args.store_key, data_source=SOURCE_NAME, field_group="TradingRules")
    _rebuild_view("TradingRules", store_key=args.store_key)
    return 0


def build_events(*, store_key: str = "openctp") -> list[dict[str, Any]]:
    with DataHub.get_instance().connect_store(store_key) as conn:
        ensure_agent_event_schema(conn)
        existing = {
            str(row[0])
            for row in conn.execute(
                "SELECT event_id FROM agent_field_change_events WHERE data_source = ?",
                (SOURCE_NAME,),
            ).fetchall()
        }
    session = _session()
    versions = _fetch_law_versions(session)
    parsed = [_parsed_version(session, row) for row in versions]
    parsed = [row for row in parsed if row["min_order_volume"] is not None]
    prior = [row for row in parsed if str(row["version"]) <= BOUNDARY_DAY.replace("-", "")]
    if not prior:
        return []
    boundary = prior[-1]
    event = _event(boundary, effective_day=BOUNDARY_DAY)
    return [] if event["event_id"] in existing else [event]


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0",
        "Referer": CSRC_BASE + "multipleFindController/indexJsp",
    })
    session.get(CSRC_BASE + "multipleFindController/indexJsp", timeout=20)
    return session


def _fetch_law_versions(session: requests.Session) -> list[dict[str, Any]]:
    data = {
        "pageNo": "1",
        "secFutrsLawName": f" AND (secFutrsLawName:*{LAW_NAME}*)",
        "body": "",
        "lawPubOrgName": "",
        "titleQry": LAW_NAME + "、",
        "keyQry": "",
        "fileno": "",
        "pubDate_from": "",
        "pubDate_thru": "",
        "isLike": "on",
        "nbr": "80",
    }
    response = session.post(CSRC_BASE + "multipleFindController/solrSearch", data=data, timeout=20)
    response.raise_for_status()
    rows = response.json().get("pageUtil", {}).get("pageList") or []
    exact = [row for row in rows if str(row.get("secFutrsLawName") or "") == LAW_NAME]
    return sorted(exact, key=lambda row: str(row.get("secFutrsLawVersion") or ""))


def _parsed_version(session: requests.Session, row: dict[str, Any]) -> dict[str, Any]:
    law_id = str(row.get("secFutrsLawId") or "")
    response = session.post(CSRC_BASE + "rdqsHeader/draftDscr", data={"secFutrsLawId": law_id}, timeout=20)
    response.raise_for_status()
    body = response.json().get("draftDscr", {}).get("secFutrsLawPO", {}).get("body") or ""
    match = re.search(r"期货合约交易指令每次最小下单数量为([0-9]+(?:\.[0-9]+)?)\s*手", body)
    return {
        "law_id": law_id,
        "version": str(row.get("secFutrsLawVersion") or ""),
        "fileno": str(row.get("fileno") or ""),
        "source_url": CSRC_BASE + "rdqsHeader/mainbody?navbarId=3&secFutrsLawId=" + law_id + "&body=",
        "source_accessed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "body": body,
        "min_order_volume": None if match is None else float(match.group(1)),
        "evidence": "" if match is None else body[max(0, match.start() - 80): match.end() + 180].strip(),
    }


def _event(version: dict[str, Any], *, effective_day: str) -> dict[str, Any]:
    value = float(version["min_order_volume"])
    event_id = "field_history_dce_trading_management_" + hashlib.sha1(
        f"DCE:*:MinLimitOrderVolume:{effective_day}:{value}:{version['law_id']}".encode("utf-8")
    ).hexdigest()[:24]
    return {
        "event_id": event_id,
        "data_source": SOURCE_NAME,
        "field_group": "TradingRules",
        "source_url": version["source_url"],
        "source_accessed_at": version["source_accessed_at"],
        "agent_name": "Agent:DCE",
        "requester_key": "field-history-dce-trading-management-rules",
        "instrument": "*",
        "instrument_label": "DCE futures exchange default",
        "instrument_type": "future",
        "scope_type": "exchange_default",
        "exchange": "DCE",
        "field_name": "MinLimitOrderVolume",
        "effective_trading_day": effective_day,
        "effective_timestamp": f"{effective_day} 09:00:00",
        "value": value,
        "contract_codes": [],
        "contract_scope_type": "all",
        "change_type": "asof_confirmed",
        "source_notice_id": str(version.get("fileno") or "DCE-trading-management-measures"),
        "raw_note": f"{LAW_NAME} version={version['version']} fileno={version.get('fileno') or ''}",
        "evidence_text": version["evidence"],
        "parser_notes": (
            "Exchange-level DCE trading-management rule. Product-specific maximum order volume "
            "remains sourced from each product business rule."
        ),
    }


if __name__ == "__main__":
    raise SystemExit(main())
