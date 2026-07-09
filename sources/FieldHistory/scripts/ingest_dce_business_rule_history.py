"""Ingest DCE product business-rule history into FieldHistory.

The current DCE product pages are not historical evidence.  For 2024+ replay
coverage, static product fields must be read from historical versions of each
品种期货业务细则 in the CSRC rules database.  This script fetches those versions,
parses explicitly stated numeric fields, writes a 2024 boundary
``asof_confirmed`` row from the latest pre-boundary rule version, and writes
later ``change`` rows only when the parsed value actually changes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
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
BOUNDARY_DAY = "2024-01-02"
SOURCE_NAME = "CSRC-rules-db"


@dataclass(frozen=True, slots=True)
class DceProductRule:
    instrument: str
    label: str
    law_name: str


DCE_PRODUCTS: tuple[DceProductRule, ...] = (
    DceProductRule("A", "黄大豆1号", "大连商品交易所黄大豆1号期货业务细则"),
    DceProductRule("B", "黄大豆2号", "大连商品交易所黄大豆2号期货业务细则"),
    DceProductRule("BB", "胶合板", "大连商品交易所胶合板期货业务细则"),
    DceProductRule("C", "玉米", "大连商品交易所玉米期货业务细则"),
    DceProductRule("CS", "玉米淀粉", "大连商品交易所玉米淀粉期货业务细则"),
    DceProductRule("EB", "苯乙烯", "大连商品交易所苯乙烯期货业务细则"),
    DceProductRule("EG", "乙二醇", "大连商品交易所乙二醇期货业务细则"),
    DceProductRule("FB", "纤维板", "大连商品交易所纤维板期货业务细则"),
    DceProductRule("I", "铁矿石", "大连商品交易所铁矿石期货业务细则"),
    DceProductRule("J", "冶金焦炭", "大连商品交易所焦炭期货业务细则"),
    DceProductRule("JD", "鲜鸡蛋", "大连商品交易所鸡蛋期货业务细则"),
    DceProductRule("JM", "焦煤", "大连商品交易所焦煤期货业务细则"),
    DceProductRule("L", "线型低密度聚乙烯", "大连商品交易所聚乙烯期货业务细则"),
    DceProductRule("LH", "生猪", "大连商品交易所生猪期货业务细则"),
    DceProductRule("LG", "原木", "大连商品交易所原木期货业务细则"),
    DceProductRule("M", "豆粕", "大连商品交易所豆粕期货业务细则"),
    DceProductRule("P", "棕榈油", "大连商品交易所棕榈油期货业务细则"),
    DceProductRule("PG", "液化石油气", "大连商品交易所液化石油气期货业务细则"),
    DceProductRule("PP", "聚丙烯", "大连商品交易所聚丙烯期货业务细则"),
    DceProductRule("RR", "粳米", "大连商品交易所粳米期货业务细则"),
    DceProductRule("V", "聚氯乙烯", "大连商品交易所聚氯乙烯期货业务细则"),
    DceProductRule("Y", "豆油", "大连商品交易所豆油期货业务细则"),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-key", default="openctp")
    parser.add_argument("--instrument", action="append", default=[])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)

    _ensure_store_registered(DataHub.get_instance(), args.store_key)
    selected = {item.upper() for item in args.instrument}
    products = [product for product in DCE_PRODUCTS if not selected or product.instrument in selected]
    if args.limit:
        products = products[: args.limit]

    events = build_events(products, store_key=args.store_key)
    print(json.dumps(_summary(events), ensure_ascii=False, indent=2))
    if args.dry_run or not events:
        return 0
    append_agent_field_change_events(events, store_key=args.store_key)
    materialize_agent_events_to_history(store_key=args.store_key, data_source=SOURCE_NAME, field_group="TradingRules")
    _rebuild_view("TradingRules", store_key=args.store_key)
    return 0


def build_events(products: list[DceProductRule], *, store_key: str = "openctp") -> list[dict[str, Any]]:
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
    accessed_at = datetime.now().astimezone().isoformat(timespec="seconds")
    events: list[dict[str, Any]] = []
    for product in products:
        versions = _fetch_law_versions(session, product.law_name)
        parsed_versions = [
            version for version in (
                _parsed_version(session, product, row, accessed_at=accessed_at)
                for row in versions
            )
            if version["values"]
        ]
        events.extend(_events_for_product(product, parsed_versions, existing=existing))
    return _dedupe_events(events)


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0",
        "Referer": CSRC_BASE + "multipleFindController/indexJsp",
    })
    session.get(CSRC_BASE + "multipleFindController/indexJsp", timeout=20)
    return session


def _fetch_law_versions(session: requests.Session, law_name: str) -> list[dict[str, Any]]:
    data = {
        "pageNo": "1",
        "secFutrsLawName": f" AND (secFutrsLawName:*{law_name}*)",
        "body": "",
        "lawPubOrgName": "",
        "titleQry": law_name + "、",
        "keyQry": "",
        "fileno": "",
        "pubDate_from": "",
        "pubDate_thru": "",
        "isLike": "on",
        "nbr": "80",
    }
    response = session.post(CSRC_BASE + "multipleFindController/solrSearch", data=data, timeout=20)
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("pageUtil", {}).get("pageList") or []
    exact = [row for row in rows if str(row.get("secFutrsLawName") or "") == law_name]
    return sorted(exact, key=lambda row: str(row.get("secFutrsLawVersion") or ""))


def _parsed_version(
    session: requests.Session,
    product: DceProductRule,
    row: dict[str, Any],
    *,
    accessed_at: str,
) -> dict[str, Any]:
    law_id = str(row.get("secFutrsLawId") or "")
    if not law_id:
        return {"values": {}}
    response = session.post(CSRC_BASE + "rdqsHeader/draftDscr", data={"secFutrsLawId": law_id}, timeout=20)
    response.raise_for_status()
    payload = response.json()
    law = payload.get("draftDscr", {}).get("secFutrsLawPO", {})
    body = str(law.get("body") or "")
    return {
        "law_id": law_id,
        "law_name": product.law_name,
        "version": str(row.get("secFutrsLawVersion") or law.get("secFutrsLawVersion") or ""),
        "fileno": str(row.get("fileno") or law.get("fileno") or ""),
        "source_url": (
            CSRC_BASE
            + "rdqsHeader/mainbody?navbarId=3&secFutrsLawId="
            + law_id
            + "&body="
        ),
        "source_accessed_at": accessed_at,
        "body": body,
        "values": _parse_values(body),
    }


def _parse_values(body: str) -> dict[str, float]:
    values: dict[str, float] = {}
    volume_multiple = _first_number(body, r"交易单位为([0-9]+(?:\.[0-9]+)?)\s*(?:吨|张|立方米)/手")
    if volume_multiple is not None:
        values["VolumeMultiple"] = volume_multiple
    price_tick = _first_number(body, r"最小变动价位为([0-9]+(?:\.[0-9]+)?)\s*元")
    if price_tick is not None:
        values["PriceTick"] = price_tick
    generic_max = _first_number(body, r"交易指令每次最大下单数量为([0-9]+(?:\.[0-9]+)?)\s*手")
    if generic_max is not None:
        values["MaxLimitOrderVolume"] = generic_max
        values["MaxMarketOrderVolume"] = generic_max
    max_limit = _first_number(body, r"限价指令每次最大下单数量为([0-9]+(?:\.[0-9]+)?)\s*手")
    if max_limit is not None:
        values["MaxLimitOrderVolume"] = max_limit
    max_market = _first_number(body, r"市价指令每次最大下单数量为([0-9]+(?:\.[0-9]+)?)\s*手")
    if max_market is not None:
        values["MaxMarketOrderVolume"] = max_market
    min_limit = _first_number(body, r"每次最小下单(?:量|数量)为([0-9]+(?:\.[0-9]+)?)\s*手")
    if min_limit is not None:
        values["MinLimitOrderVolume"] = min_limit
    return values


def _first_number(text: str, pattern: str) -> float | None:
    match = re.search(pattern, text)
    if not match:
        return None
    return float(match.group(1))


def _events_for_product(
    product: DceProductRule,
    versions: list[dict[str, Any]],
    *,
    existing: set[str],
) -> list[dict[str, Any]]:
    if not versions:
        return []
    by_version = [version for version in versions if _version_day(version) is not None]
    by_version.sort(key=lambda version: str(version["version"]))
    pre_boundary = [version for version in by_version if str(version["version"]) <= BOUNDARY_DAY.replace("-", "")]
    post_boundary = [version for version in by_version if str(version["version"]) > BOUNDARY_DAY.replace("-", "")]
    events: list[dict[str, Any]] = []
    last_values: dict[str, float] = {}
    if pre_boundary:
        boundary_version = pre_boundary[-1]
        last_values = dict(boundary_version["values"])
        for field, value in sorted(last_values.items()):
            event = _event(product, boundary_version, field, value, change_type="asof_confirmed", effective_day=BOUNDARY_DAY)
            if event["event_id"] not in existing:
                events.append(event)
    for version in post_boundary:
        effective_day = _version_day(version)
        if not effective_day:
            continue
        for field, value in sorted(version["values"].items()):
            previous = last_values.get(field)
            if previous is not None and abs(previous - value) <= 1e-12:
                continue
            event = _event(
                product,
                version,
                field,
                value,
                change_type="change",
                effective_day=effective_day,
                previous_value=previous,
            )
            if event["event_id"] not in existing:
                events.append(event)
        last_values.update(version["values"])
    return events


def _event(
    product: DceProductRule,
    version: dict[str, Any],
    field: str,
    value: float,
    *,
    change_type: str,
    effective_day: str,
    previous_value: float | None = None,
) -> dict[str, Any]:
    event_id = "field_history_dce_business_rule_" + hashlib.sha1(
        f"{product.instrument}:{field}:{effective_day}:{value}:{change_type}:{version['law_id']}".encode("utf-8")
    ).hexdigest()[:24]
    evidence = _evidence_snippet(str(version.get("body") or ""), field)
    payload: dict[str, Any] = {
        "event_id": event_id,
        "data_source": SOURCE_NAME,
        "field_group": "TradingRules",
        "source_url": version["source_url"],
        "source_accessed_at": version["source_accessed_at"],
        "agent_name": "Agent:DCE",
        "requester_key": "field-history-dce-business-rule-history",
        "instrument": product.instrument,
        "instrument_label": product.label,
        "instrument_type": "future",
        "scope_type": "product",
        "exchange": "DCE",
        "field_name": field,
        "effective_trading_day": effective_day,
        "effective_timestamp": f"{effective_day} 09:00:00",
        "value": float(value),
        "contract_codes": [],
        "contract_scope_type": "all",
        "change_type": change_type,
        "source_notice_id": str(version.get("fileno") or f"CSRC-rules-db-{version.get('version') or ''}"),
        "raw_note": f"{version['law_name']} version={version['version']} fileno={version.get('fileno') or ''}",
        "evidence_text": evidence,
        "parser_notes": (
            "Parsed from historical DCE product business-rule body in the CSRC rules database. "
            "Current DCE product pages are not used as historical evidence."
        ),
    }
    if previous_value is not None:
        payload["previous_value"] = float(previous_value)
        payload["previous_value_type"] = "declared_by_parser_prior_version"
        payload["previous_value_note"] = "Previous value from immediately prior parsed historical business-rule version."
    return payload


def _evidence_snippet(body: str, field: str) -> str:
    patterns = {
        "VolumeMultiple": r"[^。\n]*交易单位为[^。\n]*",
        "PriceTick": r"[^。\n]*最小变动价位为[^。\n]*",
        "MaxLimitOrderVolume": r"[^。\n]*(?:限价指令|交易指令)每次最大下单数量为[^。\n]*",
        "MaxMarketOrderVolume": r"[^。\n]*(?:市价指令|交易指令)每次最大下单数量为[^。\n]*",
        "MinLimitOrderVolume": r"[^。\n]*每次最小下单(?:量|数量)为[^。\n]*",
    }
    match = re.search(patterns.get(field, ""), body)
    return match.group(0).strip() if match else ""


def _version_day(version: dict[str, Any]) -> str | None:
    text = str(version.get("version") or "")
    if not re.fullmatch(r"\d{8}", text):
        return None
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}"


def _dedupe_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for event in events:
        event_id = str(event["event_id"])
        prior = by_id.get(event_id)
        if prior is not None and prior != event:
            raise ValueError(f"conflicting DCE business-rule event_id={event_id}")
        by_id[event_id] = event
    return list(by_id.values())


def _summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for event in events:
        key = f"{event['instrument']}:{event['field_name']}:{event['change_type']}"
        counts[key] = counts.get(key, 0) + 1
    return {
        "candidate_events_after_dedupe": len(events),
        "counts": dict(sorted(counts.items())),
        "sample_event_ids": [event["event_id"] for event in events[:20]],
    }


if __name__ == "__main__":
    raise SystemExit(main())
