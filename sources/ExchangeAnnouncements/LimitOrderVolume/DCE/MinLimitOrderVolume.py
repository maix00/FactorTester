"""DCE official MinLimitOrderVolume announcements.

The Guosen snapshot only lists contracts still visible in its current table.
Official exchange announcements are the authority for historical contract
scope, including contracts that may have delisted later.
"""

from __future__ import annotations

import html
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.request import Request, urlopen

from sources.ExchangeAnnouncements.field_announcements import (
    AnnouncementCandidate,
    ExchangeAnnouncementAdapter,
    register_exchange_announcement_adapter,
)


PROVIDER = "DCE"
SOURCE_KEY = "DCE/LimitOrderVolume/MinLimitOrderVolume"
NOTICE_TITLE = "关于调整部分期货合约交易指令每次最小开仓下单数量的通知"

_DCE_PRODUCT_LABELS = {
    "BZ": "纯苯",
    "EB": "苯乙烯",
    "EG": "乙二醇",
    "L": "线型低密度聚乙烯",
    "PG": "液化石油气",
    "PP": "聚丙烯",
    "V": "聚氯乙烯",
}


_NOTICE_2026_03_09 = {
    "notice_id": "大商所发〔2026〕74号",
    "source_url": "http://www.dce.com.cn/dce/content/2026/ywggytz/18627837.html",
    "source_date": "2026-03-09",
    "raw_text_excerpt": (
        "自2026年3月10日交易时（即3月9日夜盘交易小节时）起，"
        "苯乙烯期货EB2605、EB2606合约，乙二醇期货EG2604、EG2605、EG2606合约，"
        "液化石油气期货PG2604、PG2605、PG2606合约，线型低密度聚乙烯期货L2604、L2605、L2606合约，"
        "聚氯乙烯期货V2604、V2605、V2606合约，聚丙烯期货PP2604、PP2605、PP2606合约"
        "交易指令每次最小开仓下单数量调整为8手；纯苯期货BZ2604、BZ2605、BZ2606合约"
        "交易指令每次最小开仓下单数量调整为4手。"
    ),
    "effective_trading_day": "2026-03-10",
    "effective_timestamp": "2026-03-09 21:00:00",
}


OFFICIAL_NOTICES: tuple[Mapping[str, Any], ...] = (_NOTICE_2026_03_09,)


def parse_min_limit_order_records_from_text(
    text: str,
    *,
    notice: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Parse DCE MinLimitOrderVolume rules from announcement HTML/text."""
    cleaned = _clean_notice_text(text)
    records: list[dict[str, Any]] = []
    for sentence, value_text in re.findall(r"([^。；;]*?最小开仓下单数量调整为\s*(\d+)\s*手)", cleaned):
        value = int(value_text)
        contracts_by_product: dict[str, set[str]] = defaultdict(set)
        for product_code, contract_code in re.findall(r"(?<![A-Z0-9])([A-Z]{1,3})(\d{4})(?![A-Z0-9])", sentence):
            contracts_by_product[product_code.upper()].add(contract_code)
        for product_code, contract_codes in sorted(contracts_by_product.items()):
            records.append({
                "provider": PROVIDER,
                "source_key": SOURCE_KEY,
                "instrument": product_code,
                "instrument_label": _DCE_PRODUCT_LABELS.get(product_code, product_code),
                "instrument_type": "future",
                "field_name": "MinLimitOrderVolume",
                "effective_trading_day": notice["effective_trading_day"],
                "effective_timestamp": notice["effective_timestamp"],
                "value": value,
                "value_type": "int",
                "contract_codes": sorted(contract_codes),
                "source_url": notice["source_url"],
                "source_date": notice["source_date"],
                "source_notice_id": notice["notice_id"],
                "raw_note": sentence.strip(),
            })
    return records


def iter_historical_field_records() -> Iterable[dict[str, Any]]:
    """Yield normalized historical-field rows from DCE official notices."""
    for notice in OFFICIAL_NOTICES:
        text = str(notice.get("raw_text_excerpt") or "")
        yield from parse_min_limit_order_records_from_text(text, notice=notice)


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
        parsed = parse_min_limit_order_records_from_text(str(notice.get("raw_text_excerpt") or ""), notice=notice)
        if not any(row["instrument"] == product for row in parsed):
            continue
        candidates.append(AnnouncementCandidate(
            exchange="DCE",
            field_name=field_name,
            product_code=product,
            source_key=SOURCE_KEY,
            notice_id=str(notice["notice_id"]),
            title=NOTICE_TITLE,
            url=str(notice["source_url"]),
            publish_date=str(notice["source_date"]),
            matched_keywords=("最小开仓下单数量", product),
            raw_text_excerpt=str(notice["raw_text_excerpt"]),
        ))
    return tuple(candidates)


def parse(candidate: AnnouncementCandidate) -> Iterable[dict[str, Any]]:
    if candidate.field_name != "MinLimitOrderVolume":
        return ()
    notice = _notice_by_id(candidate.notice_id)
    if notice is None:
        return ()
    text = _fetch_notice_text(candidate.url) or candidate.raw_text_excerpt
    return (
        row for row in parse_min_limit_order_records_from_text(text, notice=notice)
        if row["instrument"] == candidate.product_code
    )


def _notice_by_id(notice_id: str) -> Mapping[str, Any] | None:
    for notice in OFFICIAL_NOTICES:
        if str(notice["notice_id"]) == str(notice_id):
            return notice
    return None


def _fetch_notice_text(url: str) -> str:
    try:
        request = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "http://www.dce.com.cn/",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        with urlopen(request, timeout=15) as response:
            data = response.read()
    except Exception:
        return ""
    for encoding in ("utf-8", "gb18030", "gbk"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def _clean_notice_text(text: str) -> str:
    cleaned = re.sub(r"<script\b.*?</script>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"<style\b.*?</style>", " ", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = html.unescape(cleaned)
    cleaned = re.sub(r"\s+", "", cleaned)
    return cleaned


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
