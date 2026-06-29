"""Shared helpers for discovering exchange announcements by product + field.

Raw provider pages (for example Guosen snapshots) are not enough for
contract-level historical rules because they often omit delisted contracts.
This module owns the reusable workflow:

``Product + field_name -> exchange adapter -> candidate notices -> parsed
historical_field_values -> fused field view``.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import pandas as pd

from tools.data.field_history import save_historical_field_records
from tools.data.hub import DataHub


ANNOUNCEMENT_TABLE = "exchange_field_announcements"


@dataclass(frozen=True, slots=True)
class AnnouncementCandidate:
    exchange: str
    field_name: str
    product_code: str
    source_key: str
    notice_id: str
    title: str
    url: str
    publish_date: str
    matched_keywords: tuple[str, ...]
    status: str = "candidate"
    raw_text_excerpt: str = ""


@dataclass(frozen=True, slots=True)
class ExchangeAnnouncementAdapter:
    exchange: str
    label: str
    search_url: str
    field_keywords: Mapping[str, tuple[str, ...]]
    discover: Callable[[str, str], Iterable[AnnouncementCandidate]]
    parse: Callable[[AnnouncementCandidate], Iterable[dict[str, Any]]]


_ADAPTERS: dict[str, ExchangeAnnouncementAdapter] = {}


def register_exchange_announcement_adapter(adapter: ExchangeAnnouncementAdapter) -> None:
    _ADAPTERS[adapter.exchange] = adapter


def get_exchange_announcement_adapter(exchange: str) -> ExchangeAnnouncementAdapter:
    try:
        return _ADAPTERS[_normalise_exchange(exchange)]
    except KeyError as exc:
        raise KeyError(f"no exchange announcement adapter registered for exchange={exchange}") from exc


def discover_and_sync_field_announcements(
    product: Any,
    field_name: str,
    *,
    store_key: str = "openctp",
) -> dict[str, Any]:
    """Discover exchange notices for one product/field and sync parsed events.

    Returns counts useful for logging and front-end progress messages. Missing
    parsers are not silent: candidates are stored as ``candidate``/``ignored`` so
    humans can audit coverage.
    """
    identity = product_exchange_identity(product)
    adapter = get_exchange_announcement_adapter(identity["exchange"])
    candidates = list(adapter.discover(identity["product_code"], field_name))
    save_announcement_candidates(candidates, store_key=store_key)

    records: list[dict[str, Any]] = []
    parsed_notice_ids: set[str] = set()
    for candidate in candidates:
        parsed = list(adapter.parse(candidate))
        if parsed:
            records.extend(parsed)
            parsed_notice_ids.add(candidate.notice_id)

    if records:
        save_historical_field_records(records, store_key=store_key)
        mark_announcement_status(parsed_notice_ids, "parsed", store_key=store_key)

    _save_limit_order_unified_if_relevant(field_name, store_key=store_key)
    return {
        "exchange": adapter.exchange,
        "product_code": identity["product_code"],
        "field_name": field_name,
        "candidate_count": len(candidates),
        "parsed_notice_count": len(parsed_notice_ids),
        "record_count": len(records),
    }


def save_announcement_candidates(
    candidates: Iterable[AnnouncementCandidate],
    *,
    store_key: str = "openctp",
) -> None:
    hub = DataHub.get_instance()
    hub.ensure_visits_schema()
    with hub.connect_store(store_key) as conn:
        ensure_announcement_schema(conn)
        conn.executemany(
            f"""
            INSERT OR REPLACE INTO {ANNOUNCEMENT_TABLE}
            (exchange, field_name, product_code, source_key, notice_id, title, url,
             publish_date, matched_keywords, status, raw_text_excerpt)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.exchange,
                    item.field_name,
                    item.product_code,
                    item.source_key,
                    item.notice_id,
                    item.title,
                    item.url,
                    item.publish_date,
                    json.dumps(list(item.matched_keywords), ensure_ascii=False),
                    item.status,
                    item.raw_text_excerpt,
                )
                for item in candidates
            ],
        )


def mark_announcement_status(
    notice_ids: Iterable[str],
    status: str,
    *,
    store_key: str = "openctp",
) -> None:
    ids = [notice_id for notice_id in notice_ids if notice_id]
    if not ids:
        return
    hub = DataHub.get_instance()
    hub.ensure_visits_schema()
    with hub.connect_store(store_key) as conn:
        ensure_announcement_schema(conn)
        conn.executemany(
            f"UPDATE {ANNOUNCEMENT_TABLE} SET status = ? WHERE notice_id = ?",
            [(status, notice_id) for notice_id in ids],
        )


def ensure_announcement_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {ANNOUNCEMENT_TABLE} (
            exchange TEXT NOT NULL,
            field_name TEXT NOT NULL,
            product_code TEXT NOT NULL,
            source_key TEXT NOT NULL,
            notice_id TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            publish_date TEXT,
            matched_keywords TEXT NOT NULL,
            status TEXT NOT NULL,
            raw_text_excerpt TEXT,
            PRIMARY KEY (exchange, field_name, product_code, notice_id)
        )
        """
    )


def product_exchange_identity(product: Any) -> dict[str, str]:
    text = str(getattr(product, "name", product) or "").strip()
    pipe_match = re.match(r"^(?P<exchange>[A-Z]+)\|F\|(?P<product>[A-Za-z]+)\|(?P<contract>\d{3,4})$", text)
    if pipe_match:
        return {
            "exchange": _normalise_exchange(pipe_match.group("exchange")),
            "product_code": pipe_match.group("product").upper(),
            "raw": text,
        }
    dotted_match = re.match(r"^(?P<product>[A-Za-z]+)(?:\d{3,4})?\.(?P<exchange>[A-Za-z]+)", text)
    if dotted_match:
        return {
            "exchange": _normalise_exchange(dotted_match.group("exchange")),
            "product_code": dotted_match.group("product").upper(),
            "raw": text,
        }
    raise ValueError(f"cannot infer exchange/product from {text!r}")


def _normalise_exchange(exchange: str) -> str:
    text = str(exchange or "").upper()
    aliases = {
        "SHF": "SHFE",
        "SHFE": "SHFE",
        "INE": "INE",
        "CZC": "CZCE",
        "CZCE": "CZCE",
        "DCE": "DCE",
        "CFE": "CFFEX",
        "CFFEX": "CFFEX",
        "GFE": "GFEX",
        "GFEX": "GFEX",
    }
    return aliases.get(text, text)


def _save_limit_order_unified_if_relevant(field_name: str, *, store_key: str) -> None:
    if field_name not in {"MinLimitOrderVolume", "MaxLimitOrderVolume", "MaxMarketOrderVolume"}:
        return
    from sources.FieldHistory.LimitOrderVolume import save_unified_table

    save_unified_table(store_key=store_key)


def _discover_none(product_code: str, field_name: str) -> Iterable[AnnouncementCandidate]:
    return ()


def _parse_none(candidate: AnnouncementCandidate) -> Iterable[dict[str, Any]]:
    return ()


def _register_default_adapters() -> None:
    shared_keywords = {
        "MinLimitOrderVolume": ("最小开仓下单数量", "最小下单数量", "每次最小开仓"),
        "MaxLimitOrderVolume": ("最大下单数量", "限价指令"),
        "MaxMarketOrderVolume": ("最大下单数量", "市价指令"),
    }
    for exchange, label, search_url in (
        ("SHFE", "上海期货交易所", "https://www.shfe.com.cn/news/notice/"),
        ("INE", "上海国际能源交易中心", "https://www.ine.cn/news/notice/"),
        ("CZCE", "郑州商品交易所", "http://www.czce.com.cn/cn/gyjys/jysgg/H770301index_1.htm"),
        ("CFFEX", "中国金融期货交易所", "https://www.cffex.com.cn/jysgg/"),
        ("GFEX", "广州期货交易所", "http://www.gfex.com.cn/gfex/tzts/"),
    ):
        register_exchange_announcement_adapter(ExchangeAnnouncementAdapter(
            exchange=exchange,
            label=label,
            search_url=search_url,
            field_keywords=shared_keywords,
            discover=_discover_none,
            parse=_parse_none,
        ))


_register_default_adapters()


def _load_builtin_field_adapters() -> None:
    try:
        import sources.ExchangeAnnouncements.LimitOrderVolume.DCE.MinLimitOrderVolume  # noqa: F401
    except Exception:
        # Adapter discovery must not make importing the shared helper depend on
        # one field parser being healthy. The caller will still get a clear
        # missing-adapter or parser failure when it asks for that exchange.
        return


_load_builtin_field_adapters()
