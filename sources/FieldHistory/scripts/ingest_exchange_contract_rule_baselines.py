"""Ingest official exchange contract-rule baselines for 2024+ coverage.

These rows are limited to fields directly stated by official exchange product
pages, contract tables, business rules, or listing notices.  Current broker
tables and latest OpenCTP snapshots are intentionally not used as sources.
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


EXCHANGE_ALIASES = {
    "CFFEX": "CFE",
    "CZCE": "CZC",
    "DCE": "DCE",
    "GFEX": "GFE",
    "INE": "INE",
    "SHFE": "SHF",
}

ASOF_BOUNDARY_DAY = "2024-01-02"
HEADERS = {"User-Agent": "Mozilla/5.0"}


FIELD_GROUP_BY_FIELD = {
    "OpenRatioByMoney": "TransactionFee",
    "OpenRatioByVolume": "TransactionFee",
    "CloseRatioByMoney": "TransactionFee",
    "CloseRatioByVolume": "TransactionFee",
    "CloseTodayRatioByMoney": "TransactionFee",
    "CloseTodayRatioByVolume": "TransactionFee",
    "VolumeMultiple": "TradingRules",
    "PriceTick": "TradingRules",
    "LimitUpDownRatio": "TradingRules",
    "MinLimitOrderVolume": "TradingRules",
    "MaxLimitOrderVolume": "TradingRules",
    "MaxMarketOrderVolume": "TradingRules",
    "LongMarginRatioByMoney": "Margin",
    "ShortMarginRatioByMoney": "Margin",
}


SOURCES: tuple[dict[str, Any], ...] = (
    {
        "data_source": "CFFEX",
        "exchange": "CFFEX",
        "source_url": "https://www.cffex.com.cn/cn/zz1000.html",
        "source_notice_id": "CFFEX-index-futures-contract-tables-asof-20240102",
        "effective_trading_day": "2024-01-02",
        "effective_timestamp": "2024-01-02 09:30:00",
        "change_type": "asof_confirmed",
        "raw_note": "CFFEX stock-index futures product pages state contract multipliers, minimum tick size, and daily price limit as previous trading day's settlement price +/-10%.",
        "products": {
            "IC": ("中证500指数", {"VolumeMultiple": 200.0, "PriceTick": 0.2, "LimitUpDownRatio": 0.10}),
            "IF": ("沪深300指数", {"VolumeMultiple": 300.0, "PriceTick": 0.2, "LimitUpDownRatio": 0.10}),
            "IH": ("上证50指数", {"VolumeMultiple": 300.0, "PriceTick": 0.2, "LimitUpDownRatio": 0.10}),
            "IM": ("中证1000指数", {"VolumeMultiple": 200.0, "PriceTick": 0.2, "LimitUpDownRatio": 0.10}),
        },
    },
    {
        "data_source": "CFFEX",
        "exchange": "CFFEX",
        "source_url": "https://www.cffex.com.cn/cn/2ts.html",
        "source_notice_id": "CFFEX-treasury-futures-contract-tables-asof-20240102",
        "effective_trading_day": "2024-01-02",
        "effective_timestamp": "2024-01-02 09:30:00",
        "change_type": "asof_confirmed",
        "raw_note": "CFFEX treasury-futures product tables state notional face value, minimum tick size, and daily price limits: TS +/-0.5%, TF +/-1.2%, T +/-2%, TL +/-3.5%. VolumeMultiple is the CNY value of one full price point under the 100-yuan quote convention.",
        "products": {
            "TS": ("2年期国债期货", {"VolumeMultiple": 20000.0, "PriceTick": 0.002, "LimitUpDownRatio": 0.005}),
            "TF": ("5年期国债期货", {"VolumeMultiple": 10000.0, "PriceTick": 0.005, "LimitUpDownRatio": 0.012}),
            "T": ("10年期国债期货", {"VolumeMultiple": 10000.0, "PriceTick": 0.005, "LimitUpDownRatio": 0.02}),
            "TL": ("30年期国债期货", {"VolumeMultiple": 10000.0, "PriceTick": 0.01, "LimitUpDownRatio": 0.035}),
        },
    },
    {
        "data_source": "CFFEX",
        "exchange": "CFFEX",
        "source_url": "http://www.cffex.com.cn/cn/zjssf/20240701/39212.html",
        "source_notice_id": "CFFEX-fee-schedule-20240701",
        "effective_trading_day": "2024-07-01",
        "effective_timestamp": "2024-07-01 09:30:00",
        "change_type": "change",
        "raw_note": "CFFEX fee schedule updated in July 2024 states treasury-futures transaction fees are 3 yuan/lot and close-today transactions are fee-exempt.",
        "products": {
            "TS": ("2年期国债期货", {"CloseTodayRatioByMoney": 0.0, "CloseTodayRatioByVolume": 0.0}),
            "TF": ("5年期国债期货", {"CloseTodayRatioByMoney": 0.0, "CloseTodayRatioByVolume": 0.0}),
            "T": ("10年期国债期货", {"CloseTodayRatioByMoney": 0.0, "CloseTodayRatioByVolume": 0.0}),
            "TL": ("30年期国债期货", {"CloseTodayRatioByMoney": 0.0, "CloseTodayRatioByVolume": 0.0}),
        },
    },
    {
        "data_source": "DCE",
        "exchange": "DCE",
        "source_url": "https://www.dce.com.cn/dce/channel/list/133.html",
        "source_notice_id": "DCE-L-product-page-asof-20240102",
        "effective_trading_day": "2024-01-02",
        "effective_timestamp": "2024-01-02 09:00:00",
        "change_type": "asof_confirmed",
        "raw_note": "DCE polyethylene futures product page states trading unit 5 tons/lot and minimum tick 1 yuan/ton.",
        "products": {
            "L": ("线型低密度聚乙烯", {"VolumeMultiple": 5.0, "PriceTick": 1.0}),
        },
    },
    {
        "data_source": "INE",
        "exchange": "INE",
        "source_url": "https://www.ine.cn/products/futures/index_f/ec_f/",
        "source_notice_id": "INE-EC-product-spec-asof-20240102",
        "effective_trading_day": "2024-01-02",
        "effective_timestamp": "2024-01-02 09:00:00",
        "change_type": "asof_confirmed",
        "raw_note": "INE SCFIS Europe futures product page states contract multiplier 50 yuan/point, pre-2026-05-11 minimum tick 0.1 point, and price limit no more than previous trading day's settlement price +/-10%.",
        "products": {
            "EC": ("SCFIS欧线", {"VolumeMultiple": 50.0, "PriceTick": 0.1, "LimitUpDownRatio": 0.10}),
        },
    },
    {
        "data_source": "INE",
        "exchange": "INE",
        "source_url": "https://www.ine.cn/products/futures/index_f/ec_f/",
        "source_notice_id": "INE-EC-price-tick-change-20260511",
        "effective_trading_day": "2026-05-11",
        "effective_timestamp": "2026-05-11 09:00:00",
        "change_type": "change",
        "raw_note": "INE SCFIS Europe futures product page states minimum tick changed from 0.1 point to 0.5 point from 2026-05-11.",
        "products": {
            "EC": ("SCFIS欧线", {"PriceTick": 0.5}),
        },
    },
    {
        "data_source": "GFEX",
        "exchange": "GFEX",
        "source_url": "https://www.gfex.com.cn/gfex/pzxz/202307/599e991d72de4d518e029a3138bfc517/files/%E5%B9%BF%E5%B7%9E%E6%9C%9F%E8%B4%A7%E4%BA%A4%E6%98%93%E6%89%80%E7%A2%B3%E9%85%B8%E9%94%82%E6%9C%9F%E8%B4%A7%E3%80%81%E6%9C%9F%E6%9D%83%E4%B8%9A%E5%8A%A1%E7%BB%86%E5%88%99.pdf",
        "source_notice_id": "GFEX-LC-business-rules-asof-20240102",
        "effective_trading_day": "2024-01-02",
        "effective_timestamp": "2024-01-02 09:00:00",
        "change_type": "asof_confirmed",
        "raw_note": "GFEX lithium-carbonate futures contract and business rules state trading unit 1 ton/lot, minimum tick 50 yuan/ton, pre-delivery-month price limit 4%, maximum order quantity 1000 lots, and minimum order quantity 1 lot.",
        "products": {
            "LC": ("碳酸锂", {
                "VolumeMultiple": 1.0,
                "PriceTick": 50.0,
                "LimitUpDownRatio": 0.04,
                "MinLimitOrderVolume": 1.0,
                "MaxLimitOrderVolume": 1000.0,
                "MaxMarketOrderVolume": 1000.0,
            }),
        },
    },
    {
        "data_source": "GFEX",
        "exchange": "GFEX",
        "source_url": "https://www.gfex.com.cn/gfex/pzxz/202404/06c565bfcb5b4c0f8ecbf738e6055900.shtml",
        "source_notice_id": "GFEX-SI-business-rules-asof-20240102",
        "effective_trading_day": "2024-01-02",
        "effective_timestamp": "2024-01-02 09:00:00",
        "change_type": "asof_confirmed",
        "raw_note": "GFEX industrial-silicon futures contract and business rules state trading unit 5 tons/lot, minimum tick 5 yuan/ton, pre-delivery-month price limit 4%, maximum order quantity 1000 lots, and minimum order quantity 1 lot.",
        "products": {
            "SI": ("工业硅", {
                "VolumeMultiple": 5.0,
                "PriceTick": 5.0,
                "LimitUpDownRatio": 0.04,
                "MinLimitOrderVolume": 1.0,
                "MaxLimitOrderVolume": 1000.0,
                "MaxMarketOrderVolume": 1000.0,
            }),
        },
    },
    {
        "data_source": "GFEX",
        "exchange": "GFEX",
        "source_url": "https://www.gfex.com.cn/gfex/tzts/202412/34bc2f9dbfc34b4b81e1a043ff526589.shtml",
        "source_notice_id": "GFEX-PS-listing-20241226",
        "effective_trading_day": "2024-12-26",
        "effective_timestamp": "2024-12-26 09:00:00",
        "change_type": "baseline",
        "raw_note": "GFEX polysilicon futures listing notice and product rules state trading unit 3 tons/lot, minimum tick 5 yuan/ton, trading margin 9%, next-day normal price limit 7%, maximum order quantity 1000 lots, and minimum order quantity 1 lot.",
        "products": {
            "PS": ("多晶硅", {
                "VolumeMultiple": 3.0,
                "PriceTick": 5.0,
                "LongMarginRatioByMoney": 0.09,
                "ShortMarginRatioByMoney": 0.09,
                "LimitUpDownRatio": 0.07,
                "MinLimitOrderVolume": 1.0,
                "MaxLimitOrderVolume": 1000.0,
                "MaxMarketOrderVolume": 1000.0,
            }),
        },
    },
    {
        "data_source": "GFEX",
        "exchange": "GFEX",
        "source_url": "https://www.gfex.com.cn/gfex/tzts/202508/4d8af56888c84490b525d5d8fdd729f6.shtml",
        "source_notice_id": "GFEX-PT-listing-20251127",
        "effective_trading_day": "2025-11-27",
        "effective_timestamp": "2025-11-27 09:00:00",
        "change_type": "baseline",
        "raw_note": "GFEX platinum futures listing notice and product rules state trading unit 1000 grams/lot, minimum tick 0.05 yuan/gram, trading margin 9%, next-day normal price limit 7%, maximum order quantity 1000 lots, and minimum order quantity 1 lot.",
        "products": {
            "PT": ("铂", {
                "VolumeMultiple": 1000.0,
                "PriceTick": 0.05,
                "LongMarginRatioByMoney": 0.09,
                "ShortMarginRatioByMoney": 0.09,
                "LimitUpDownRatio": 0.07,
                "MinLimitOrderVolume": 1.0,
                "MaxLimitOrderVolume": 1000.0,
                "MaxMarketOrderVolume": 1000.0,
            }),
        },
    },
    {
        "data_source": "GFEX",
        "exchange": "GFEX",
        "source_url": "https://www.gfex.com.cn/gfex/tzts/202508/5ff7c8717a4a44708e650a08b198254f.shtml",
        "source_notice_id": "GFEX-PD-listing-20251127",
        "effective_trading_day": "2025-11-27",
        "effective_timestamp": "2025-11-27 09:00:00",
        "change_type": "baseline",
        "raw_note": "GFEX palladium futures listing notice and product rules state trading unit 1000 grams/lot, minimum tick 0.05 yuan/gram, trading margin 9%, next-day normal price limit 7%, maximum order quantity 1000 lots, and minimum order quantity 1 lot.",
        "products": {
            "PD": ("钯", {
                "VolumeMultiple": 1000.0,
                "PriceTick": 0.05,
                "LongMarginRatioByMoney": 0.09,
                "ShortMarginRatioByMoney": 0.09,
                "LimitUpDownRatio": 0.07,
                "MinLimitOrderVolume": 1.0,
                "MaxLimitOrderVolume": 1000.0,
                "MaxMarketOrderVolume": 1000.0,
            }),
        },
    },
    {
        "data_source": "SHFE",
        "exchange": "SHFE",
        "source_url": "https://www.shfe.com.cn/index/othercontents/2025_AD/FJ-1.pdf",
        "source_notice_id": "SHFE-AD-contract-table-20250610",
        "effective_trading_day": "2025-06-10",
        "effective_timestamp": "2025-06-10 09:00:00",
        "change_type": "baseline",
        "raw_note": "SHFE cast-aluminium-alloy futures contract table states trading unit 10 tons/lot, tick size 5 yuan/ton, normal price limit +/-3%, and minimum margin 5%; listing notice states actual listing risk parameters separately.",
        "products": {
            "AD": ("铸造铝合金", {
                "VolumeMultiple": 10.0,
                "PriceTick": 5.0,
                "LimitUpDownRatio": 0.03,
                "LongMarginRatioByMoney": 0.05,
                "ShortMarginRatioByMoney": 0.05,
            }),
        },
    },
    {
        "data_source": "SHFE",
        "exchange": "SHFE",
        "source_url": "https://www.shfe.com.cn/index/othercontents/2025_AD/manual.pdf",
        "source_notice_id": "SHFE-AD-trading-manual-order-volume-20250610",
        "effective_trading_day": "2025-06-10",
        "effective_timestamp": "2025-06-10 09:00:00",
        "change_type": "baseline",
        "raw_note": "SHFE cast-aluminium-alloy trading manual states limit orders have maximum order quantity 500 lots and trading instructions have minimum order quantity 1 lot.",
        "products": {
            "AD": ("铸造铝合金", {
                "MinLimitOrderVolume": 1.0,
                "MaxLimitOrderVolume": 500.0,
                "MaxMarketOrderVolume": 0.0,
            }),
        },
    },
    {
        "data_source": "SHFE",
        "exchange": "SHFE",
        "source_url": "https://www.shfe.com.cn/publicnotice/notice/202508/t20250818_828697.html",
        "source_notice_id": "上期发〔2025〕234号",
        "effective_trading_day": "2025-09-10",
        "effective_timestamp": "2025-09-10 09:00:00",
        "change_type": "baseline",
        "raw_note": "胶版印刷纸期货自2025年9月10日起上市交易；交易手续费为成交金额的万分之一，平今仓手续费为成交金额的万分之一。",
        "products": {
            "OP": ("胶版印刷纸", {
                "OpenRatioByMoney": 0.0001,
                "OpenRatioByVolume": 0.0,
                "CloseRatioByMoney": 0.0001,
                "CloseRatioByVolume": 0.0,
                "CloseTodayRatioByMoney": 0.0001,
                "CloseTodayRatioByVolume": 0.0,
            }),
        },
    },
    {
        "data_source": "SHFE",
        "exchange": "SHFE",
        "source_url": "https://www.shfe.com.cn/index/othercontents/FUTURES-OPTIONS/FJ1.pdf",
        "source_notice_id": "SHFE-OP-contract-table-20250828",
        "effective_trading_day": "2025-08-28",
        "effective_timestamp": "2025-08-28 09:00:00",
        "change_type": "baseline",
        "raw_note": "SHFE offset printing paper futures contract table states trading unit 40 tons/lot, tick size 2 yuan/ton, normal price limit +/-4%, and minimum margin 5%.",
        "products": {
            "OP": ("胶版印刷纸", {
                "VolumeMultiple": 40.0,
                "PriceTick": 2.0,
                "LimitUpDownRatio": 0.04,
                "LongMarginRatioByMoney": 0.05,
                "ShortMarginRatioByMoney": 0.05,
            }),
        },
    },
    {
        "data_source": "SHFE",
        "exchange": "SHFE",
        "source_url": "https://www.shfe.com.cn/index/othercontents/FUTURES-OPTIONS/manual.pdf",
        "source_notice_id": "SHFE-OP-trading-manual-order-volume-20250828",
        "effective_trading_day": "2025-08-28",
        "effective_timestamp": "2025-08-28 09:00:00",
        "change_type": "baseline",
        "raw_note": "SHFE offset printing paper futures trading manual states exchange order-volume limits; futures follow SHFE futures instruction baseline while options have a separate 100-lot maximum.",
        "products": {
            "OP": ("胶版印刷纸", {
                "MinLimitOrderVolume": 1.0,
                "MaxLimitOrderVolume": 500.0,
                "MaxMarketOrderVolume": 0.0,
            }),
        },
    },
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-key", default="openctp")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    events = build_events(store_key=args.store_key)
    if not args.dry_run and events:
        append_agent_field_change_events(events, store_key=args.store_key)
        for field_group in sorted({event["field_group"] for event in events}):
            materialize_agent_events_to_history(store_key=args.store_key, field_group=field_group)
            _rebuild_view(field_group, store_key=args.store_key)
    print(json.dumps({
        "candidate_events": len(events),
        "inserted": 0 if args.dry_run else len(events),
        "sample_event_ids": [event["event_id"] for event in events[:30]],
    }, ensure_ascii=False, indent=2))
    return 0


def build_events(*, store_key: str = "openctp") -> list[dict[str, Any]]:
    hub = DataHub.get_instance()
    _ensure_store_registered(hub, store_key)
    accessed_at = datetime.now().astimezone().isoformat(timespec="seconds")
    with hub.connect_store(store_key) as conn:
        ensure_agent_event_schema(conn)
        existing = {
            tuple(row)
            for row in conn.execute(
                """
                SELECT data_source, field_group, instrument, instrument_type, field_name,
                       effective_trading_day, COALESCE(effective_timestamp, ''),
                       COALESCE(contract_scope_type, 'all'), contract_codes_json,
                       COALESCE(contract_code_start, ''), COALESCE(contract_code_end, ''),
                       value_json
                FROM agent_field_change_events
                """
            ).fetchall()
        }
    sources = list(SOURCES)
    sources.extend(_czce_contract_spec_sources())
    sources.extend(_official_product_spec_sources(accessed_at=accessed_at))
    events = [
        event
        for source in sources
        for instrument, (label, fields) in source["products"].items()
        for field_name, value in fields.items()
        if _event_key(event := _event(source, instrument, label, field_name, float(value), accessed_at=accessed_at)) not in existing
    ]
    return events


def _czce_contract_spec_sources() -> list[dict[str, Any]]:
    rows = (
        ("AP", "苹果", "https://www.czce.com.cn/cn/sspz/pg/H077002021index_1.htm", "2024-01-02", "asof_confirmed", 10.0, 1.0),
        ("CJ", "红枣", "https://www.czce.com.cn/cn/sspz/hzqh/H077002022index_1.htm", "2024-01-02", "asof_confirmed", 5.0, 5.0),
        ("CY", "棉纱", "https://www.czce.com.cn/cn/sspz/miansha/H077002019index_1.htm", "2024-01-02", "asof_confirmed", 5.0, 5.0),
        ("FG", "玻璃", "https://www.czce.com.cn/cn/sspz/bl/H077002009index_1.htm", "2024-01-02", "asof_confirmed", 20.0, 1.0),
        ("JR", "粳稻", "https://www.czce.com.cn/cn/sspz/jd/bzhy/qhhy/H077002013001001index_1.htm", "2024-01-02", "asof_confirmed", 20.0, 1.0),
        ("LR", "晚籼稻", "https://www.czce.com.cn/cn/sspz/wxd/H077002014index_1.htm", "2024-01-02", "asof_confirmed", 20.0, 1.0),
        ("PF", "短纤", "https://www.czce.com.cn/cn/sspz/dxqh/H077002025index_1.htm", "2024-01-02", "asof_confirmed", 5.0, 2.0),
        ("PK", "花生", "https://www.czce.com.cn/cn/sspz/hsqh/bzhy/qhhy/H077002026002001index_1.htm", "2024-01-02", "asof_confirmed", 5.0, 2.0),
        ("PL", "丙烯", "https://www.czce.com.cn/cn/sspz/bxqhqq/H077002030index_1.htm", "2025-07-22", "baseline", 20.0, 1.0),
        ("PR", "瓶片", "https://www.czce.com.cn/cn/sspz/ppqh/H077002029index_1.htm", "2024-08-30", "baseline", 15.0, 2.0),
        ("PX", "对二甲苯", "https://www.czce.com.cn/cn/sspz/dejbqhqq/H077002027index_1.htm", "2024-01-02", "asof_confirmed", 5.0, 2.0),
        ("RM", "菜籽粕", "https://www.czce.com.cn/cn/sspz/czp/H077002011index_1.htm", "2024-01-02", "asof_confirmed", 10.0, 1.0),
        ("RS", "油菜籽", "https://www.czce.com.cn/cn/sspz/ycz/H077002010index_1.htm", "2024-01-02", "asof_confirmed", 10.0, 1.0),
        ("SA", "纯碱", "https://www.czce.com.cn/cn/sspz/cjqh/H077002024index_1.htm", "2024-01-02", "asof_confirmed", 20.0, 1.0),
        ("SF", "硅铁", "https://www.czce.com.cn/cn/sspz/gt/H077002017index_1.htm", "2024-01-02", "asof_confirmed", 5.0, 2.0),
        ("SH", "烧碱", "https://www.czce.com.cn/cn/sspz/sjqhqq/H077002028index_1.htm", "2024-01-02", "asof_confirmed", 30.0, 1.0),
        ("SM", "锰硅", "https://www.czce.com.cn/cn/sspz/meng/H077002020index_1.htm", "2024-01-02", "asof_confirmed", 5.0, 2.0),
        ("UR", "尿素", "https://www.czce.com.cn/cn/sspz/nsqh/bzhy/qhhy/H077002023002001index_1.htm", "2024-01-02", "asof_confirmed", 20.0, 1.0),
    )
    sources: list[dict[str, Any]] = []
    for instrument, label, url, effective_day, change_type, volume_multiple, price_tick in rows:
        sources.append({
            "data_source": "CZCE",
            "exchange": "CZCE",
            "source_url": url,
            "source_notice_id": f"CZCE-{instrument}-contract-spec-{effective_day}",
            "effective_trading_day": effective_day,
            "effective_timestamp": f"{effective_day} 09:00:00",
            "change_type": change_type,
            "raw_note": (
                f"CZCE official futures contract page for {label} states trading unit "
                f"{volume_multiple:g} tons/lot or contract-specific unit and minimum tick {price_tick:g} yuan/unit."
            ),
            "products": {
                instrument: (label, {"VolumeMultiple": volume_multiple, "PriceTick": price_tick}),
            },
        })
    return sources


def _official_product_spec_sources(*, accessed_at: str) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for exchange, instrument, label, url in _official_product_spec_urls():
        if exchange == "INE" and instrument == "EC":
            continue
        spec = _fetch_official_product_spec(exchange=exchange, instrument=instrument, url=url)
        if spec is None:
            continue
        effective_day = ASOF_BOUNDARY_DAY
        effective_timestamp = f"{ASOF_BOUNDARY_DAY} 09:00:00"
        change_type = "asof_confirmed"
        sources.append({
            "data_source": exchange,
            "exchange": exchange,
            "source_url": url,
            "source_notice_id": f"{exchange}-{instrument}-product-spec-{spec['data_standard'] or 'undated'}",
            "effective_trading_day": effective_day,
            "effective_timestamp": effective_timestamp,
            "change_type": change_type,
            "raw_note": (
                f"{exchange} official product contract page states {instrument} "
                f"contract size as {spec.get('contract_size_text') or spec.get('contract_multiplier_text')}, "
                f"minimum tick as {spec.get('tick_text')}, and price limit as {spec['range_text']}. "
                f"Parsed at {accessed_at}."
            ),
            "products": {
                instrument: (label, _spec_fields(spec)),
            },
        })
    return sources


def _official_product_spec_urls() -> tuple[tuple[str, str, str, str], ...]:
    shfe = "http://www.shfe.com.cn/products/futures"
    ine = "https://www.ine.cn/products/futures"
    return (
        ("SHFE", "AG", "白银", f"{shfe}/metal/ferrousandpreciousmetal/ag_f/"),
        ("SHFE", "AU", "黄金", f"{shfe}/metal/ferrousandpreciousmetal/au_f/"),
        ("SHFE", "HC", "热轧卷板", f"{shfe}/metal/ferrousandpreciousmetal/hc_f/"),
        ("SHFE", "RB", "螺纹钢", f"{shfe}/metal/ferrousandpreciousmetal/rb_f/"),
        ("SHFE", "SS", "不锈钢", f"{shfe}/metal/ferrousandpreciousmetal/ss_f/"),
        ("SHFE", "WR", "线材", f"{shfe}/metal/ferrousandpreciousmetal/wr_f/"),
        ("SHFE", "AL", "铝", f"{shfe}/metal/nonferrousmetal/al_f/"),
        ("SHFE", "AO", "氧化铝", f"{shfe}/metal/nonferrousmetal/ao_f/"),
        ("SHFE", "CU", "阴极铜", f"{shfe}/metal/nonferrousmetal/cu_f/"),
        ("SHFE", "NI", "镍", f"{shfe}/metal/nonferrousmetal/ni_f/"),
        ("SHFE", "PB", "铅", f"{shfe}/metal/nonferrousmetal/pb_f/"),
        ("SHFE", "SN", "锡", f"{shfe}/metal/nonferrousmetal/sn_f/"),
        ("SHFE", "ZN", "锌", f"{shfe}/metal/nonferrousmetal/zn_f/"),
        ("SHFE", "BR", "丁二烯橡胶", f"{shfe}/energyandchemical/br_f/"),
        ("SHFE", "BU", "石油沥青", f"{shfe}/energyandchemical/bu_f/"),
        ("SHFE", "FU", "燃料油", f"{shfe}/energyandchemical/fu_f/"),
        ("SHFE", "RU", "天然橡胶", f"{shfe}/energyandchemical/ru_f/"),
        ("SHFE", "SP", "纸浆", f"{shfe}/energyandchemical/sp_f/"),
        ("INE", "BC", "国际铜", f"{ine}/metal/nonferrousmetal/bc_f/standard_bc_f/202312/t20231205_802543.html"),
        ("INE", "EC", "SCFIS欧线", f"{ine}/index_f/ec_f/"),
        ("INE", "LU", "低硫燃料油", f"{ine}/energyandchemical/lu_f/"),
        ("INE", "NR", "20号胶", f"{ine}/energyandchemical/nr_f/"),
        ("INE", "SC", "原油", f"{ine}/energyandchemical/sc_f/"),
    )


def _fetch_official_product_spec(*, exchange: str, instrument: str, url: str) -> dict[str, Any] | None:
    response = requests.get(url, headers=HEADERS, timeout=20)
    response.raise_for_status()
    text = response.text
    symbol = _regex_value(text, "ContractSymbol")
    if symbol and symbol.upper() != instrument:
        raise ValueError(f"{exchange} product spec URL mismatch: expected {instrument}, got {symbol}")
    contract_size_text = _regex_value(text, "ContractSize") or _legacy_label_value(text, "交易单位")
    contract_multiplier_text = _regex_value(text, "ContractMultiplier") or _legacy_label_value(text, "合约乘数")
    tick_text = _regex_value(text, "MinimumPriceFluctuation") or _legacy_label_value(text, "最小变动价位")
    range_text = _regex_value(text, "RangeofPriceLimit") or _legacy_label_value(text, "涨跌停板幅度")
    if not range_text:
        return None
    data_standard = _regex_value(text, "data_standard") or _legacy_publish_date(text)
    return {
        "contract_size_text": contract_size_text,
        "contract_multiplier_text": contract_multiplier_text,
        "tick_text": tick_text,
        "volume_multiple": _contract_volume_multiple(contract_size_text or contract_multiplier_text),
        "price_tick": _price_tick(tick_text),
        "range_text": range_text,
        "limit_ratio": _price_limit_ratio(range_text),
        "data_standard": data_standard,
    }


def _spec_fields(spec: dict[str, Any]) -> dict[str, float]:
    fields = {"LimitUpDownRatio": float(spec["limit_ratio"])}
    if spec.get("volume_multiple") is not None:
        fields["VolumeMultiple"] = float(spec["volume_multiple"])
    if spec.get("price_tick") is not None:
        fields["PriceTick"] = float(spec["price_tick"])
    return fields


def _regex_value(text: str, key: str) -> str:
    match = re.search(r'"' + re.escape(key) + r'"\s*:\s*"([^"]*)"', text)
    return match.group(1).strip() if match else ""


def _legacy_label_value(text: str, label: str) -> str:
    plain = re.sub(r"<[^>]+>", "\n", text)
    lines = [line.strip() for line in plain.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if line == label and index + 1 < len(lines):
            return lines[index + 1]
    return ""


def _legacy_publish_date(text: str) -> str:
    plain = re.sub(r"<[^>]+>", "\n", text)
    lines = [line.strip() for line in plain.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        match = re.search(r"\d{4}-\d{2}-\d{2}", line + " " + (lines[index + 1] if index + 1 < len(lines) else ""))
        if "发布日期" in line and match:
            return match.group(0)
    return ""


def _price_limit_ratio(text: str) -> float:
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*%", text)
    if not match:
        raise ValueError(f"cannot parse price-limit ratio from {text!r}")
    return float(match.group(1)) / 100.0


def _contract_volume_multiple(text: str) -> float | None:
    if not text:
        return None
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", text.replace(",", ""))
    if not match:
        return None
    return float(match.group(1))


def _price_tick(text: str) -> float | None:
    if not text:
        return None
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", text.replace(",", ""))
    if not match:
        return None
    return float(match.group(1))


def _event(
    source: dict[str, Any],
    instrument: str,
    label: str,
    field_name: str,
    value: float,
    *,
    accessed_at: str,
) -> dict[str, Any]:
    field_group = FIELD_GROUP_BY_FIELD[field_name]
    event_id = "field_history_contract_rule_" + hashlib.sha1(
        (
            f"{source['source_notice_id']}:{instrument}:{field_group}:{field_name}:"
            f"{source['effective_trading_day']}:{value}"
        ).encode("utf-8")
    ).hexdigest()[:24]
    exchange = str(source["exchange"])
    return {
        "event_id": event_id,
        "data_source": source["data_source"],
        "field_group": field_group,
        "source_url": source["source_url"],
        "source_accessed_at": accessed_at,
        "agent_name": f"Agent:{source['data_source']}",
        "requester_key": "field-history-official-contract-rules",
        "instrument": instrument,
        "instrument_label": label,
        "instrument_type": "future",
        "scope_type": "product",
        "exchange": EXCHANGE_ALIASES.get(exchange, exchange),
        "field_name": field_name,
        "effective_trading_day": source["effective_trading_day"],
        "effective_timestamp": source["effective_timestamp"],
        "value": value,
        "contract_codes": [],
        "contract_scope_type": "all",
        "change_type": source["change_type"],
        "source_notice_id": source["source_notice_id"],
        "raw_note": source["raw_note"],
        "evidence_text": source["raw_note"],
        "parser_notes": (
            "Official exchange contract-rule baseline. Product pages and contract "
            "tables provide normal/base values; path-dependent limit moves, holiday "
            "overrides, and lifecycle delivery-month overlays are handled by rule "
            "engines or separate dated notices."
        ),
    }


def _event_key(event: dict[str, Any]) -> tuple[Any, ...]:
    return (
        event["data_source"],
        event["field_group"],
        event["instrument"],
        event["instrument_type"],
        event["field_name"],
        event["effective_trading_day"],
        event.get("effective_timestamp") or "",
        event.get("contract_scope_type") or "all",
        json.dumps(event.get("contract_codes") or [], ensure_ascii=False),
        event.get("contract_code_start") or "",
        event.get("contract_code_end") or "",
        json.dumps(event["value"], ensure_ascii=False),
    )


if __name__ == "__main__":
    raise SystemExit(main())
