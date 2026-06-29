"""DCE official MinLimitOrderVolume announcements.

The Guosen snapshot only lists contracts still visible in its current table.
Official exchange announcements are the authority for historical contract
scope, including contracts that may have delisted later.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from sources.ExchangeAnnouncements.field_announcements import (
    AnnouncementCandidate,
    ExchangeAnnouncementAdapter,
    register_exchange_announcement_adapter,
)


PROVIDER = "DCE"
SOURCE_KEY = "DCE/LimitOrderVolume/MinLimitOrderVolume"


_NOTICE_2026_03_09 = {
    "notice_id": "大商所发〔2026〕74号",
    "source_url": "http://www.dce.com.cn/dce/content/2026/ywggytz/18627837.html",
    "source_date": "2026-03-09",
    "raw_note": (
        "自2026年3月10日交易时（即3月9日夜盘交易小节时）起，乙二醇、液化石油气、"
        "聚乙烯、聚氯乙烯、聚丙烯期货2604、2605和2606合约，苯乙烯期货2605和2606合约，"
        "纯苯期货2604、2605和2606合约每次最小开仓下单数量调整。"
    ),
    "effective_trading_day": "2026-03-10",
    "effective_timestamp": "2026-03-09 21:00:00",
    "rules": [
        {"instrument": "EG", "instrument_label": "乙二醇", "contract_codes": ["2604", "2605", "2606"], "value": 8},
        {"instrument": "PG", "instrument_label": "液化石油气", "contract_codes": ["2604", "2605", "2606"], "value": 8},
        {"instrument": "L", "instrument_label": "聚乙烯", "contract_codes": ["2604", "2605", "2606"], "value": 8},
        {"instrument": "V", "instrument_label": "聚氯乙烯", "contract_codes": ["2604", "2605", "2606"], "value": 8},
        {"instrument": "PP", "instrument_label": "聚丙烯", "contract_codes": ["2604", "2605", "2606"], "value": 8},
        {"instrument": "EB", "instrument_label": "苯乙烯", "contract_codes": ["2605", "2606"], "value": 8},
        {"instrument": "BZ", "instrument_label": "纯苯", "contract_codes": ["2604", "2605", "2606"], "value": 4},
    ],
}


OFFICIAL_NOTICES: tuple[Mapping[str, Any], ...] = (_NOTICE_2026_03_09,)


def iter_historical_field_records() -> Iterable[dict[str, Any]]:
    """Yield normalized historical-field rows from DCE official notices."""
    for notice in OFFICIAL_NOTICES:
        for rule in notice["rules"]:
            yield {
                "provider": PROVIDER,
                "source_key": SOURCE_KEY,
                "instrument": rule["instrument"],
                "instrument_label": rule["instrument_label"],
                "instrument_type": "future",
                "field_name": "MinLimitOrderVolume",
                "effective_trading_day": notice["effective_trading_day"],
                "effective_timestamp": notice["effective_timestamp"],
                "value": rule["value"],
                "value_type": "int",
                "contract_codes": rule["contract_codes"],
                "source_url": notice["source_url"],
                "source_date": notice["source_date"],
                "source_notice_id": notice["notice_id"],
                "raw_note": notice["raw_note"],
            }


def sync_sqlite_store(*, store_key: str = "openctp") -> str:
    """Write DCE official MinLimitOrderVolume records to historical_field_values."""
    from tools.data.field_history import save_historical_field_records

    return save_historical_field_records(
        list(iter_historical_field_records()),
        store_key=store_key,
        replace_provider=PROVIDER,
        replace_source_key=SOURCE_KEY,
    )


def discover(product_code: str, field_name: str) -> Iterable[AnnouncementCandidate]:
    if field_name != "MinLimitOrderVolume":
        return ()
    product = str(product_code or "").upper()
    candidates: list[AnnouncementCandidate] = []
    for notice in OFFICIAL_NOTICES:
        matched_rules = [
            rule for rule in notice["rules"]
            if str(rule["instrument"]).upper() == product
        ]
        if not matched_rules:
            continue
        candidates.append(AnnouncementCandidate(
            exchange="DCE",
            field_name=field_name,
            product_code=product,
            source_key=SOURCE_KEY,
            notice_id=str(notice["notice_id"]),
            title="关于调整部分期货合约每次最小开仓下单数量的通知",
            url=str(notice["source_url"]),
            publish_date=str(notice["source_date"]),
            matched_keywords=("最小开仓下单数量", product),
            raw_text_excerpt=str(notice["raw_note"]),
        ))
    return tuple(candidates)


def parse(candidate: AnnouncementCandidate) -> Iterable[dict[str, Any]]:
    if candidate.field_name != "MinLimitOrderVolume":
        return ()
    return (
        row for row in iter_historical_field_records()
        if row["instrument"] == candidate.product_code
        and row["source_notice_id"] == candidate.notice_id
    )


register_exchange_announcement_adapter(ExchangeAnnouncementAdapter(
    exchange="DCE",
    label="大连商品交易所",
    search_url="http://www.dce.com.cn/dce/ywggytz/ywggytz.htm",
    field_keywords={
        "MinLimitOrderVolume": ("最小开仓下单数量", "最小下单数量", "每次最小开仓"),
        "MaxLimitOrderVolume": ("最大下单数量", "限价指令"),
        "MaxMarketOrderVolume": ("最大下单数量", "市价指令"),
    },
    discover=discover,
    parse=parse,
))
