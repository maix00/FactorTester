"""Contract-list and contract-price catalog projections."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, cast

import pandas as pd

from server.modules.shared.price_data_helpers import (
    format_price_row,
    open_interest_column,
)
from server.modules.shared.price_services import (
    available_freq_names_for_product,
    available_sources_for_product,
    cached_products,
    contract_data_path_for,
    contract_has_data,
    find_contract_product,
    find_product,
    product_public_fields,
    supports_term_structure,
)
from tools.products.product_utils import get_product_contracts

from .errors import ProductMarketDataError
from .ranges import range_bound
from .sampling import bounded_ohlcv_rows


def contract_listing(
    product_name: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    if not product_name:
        raise ProductMarketDataError("缺少 product 参数")
    product = find_product(cached_products(), product_name)
    if product is None:
        raise ProductMarketDataError(f"未找到品种: {product_name}", 404)
    if not supports_term_structure(product):
        return {
            "success": True,
            "product": product_name,
            "supports_term_structure": False,
            "has_term_structure": False,
            "contracts": [],
            "naming_schemes": [],
        }
    contracts = get_product_contracts(
        product,
        start_date=start_date,
        end_date=end_date,
    )
    for contract in contracts:
        contract["has_data"] = contract_has_data(contract["uid"])
    naming_schemes = sorted({
        str(contract.get("naming_scheme") or "").strip()
        for contract in contracts
        if str(contract.get("naming_scheme") or "").strip()
    })
    return {
        "success": True,
        "product": product_name,
        "supports_term_structure": True,
        "has_term_structure": True,
        "contracts": contracts,
        "naming_schemes": naming_schemes,
        "fields": product_public_fields(product),
    }


def contract_price_series(payload: Mapping[str, Any]) -> dict[str, Any]:
    contract_uid = str(payload.get("contract_uid") or "")
    if not contract_uid:
        raise ProductMarketDataError("缺少 contract_uid")
    contract_product = find_contract_product(contract_uid)
    available_freqs = (
        available_freq_names_for_product(contract_product)
        if contract_product else []
    )
    available_sources = (
        available_sources_for_product(contract_product)
        if contract_product else []
    )
    requested_source = str(payload.get("data_source") or "").strip()
    available_source_ids = {
        str(item.get("alias") or "").strip()
        for item in available_sources
        if str(item.get("alias") or "").strip()
    }
    if requested_source and requested_source not in available_source_ids:
        raise ProductMarketDataError(
            f"合约不提供所选数据源: {requested_source}", 400,
        )
    contract_file = contract_data_path_for(
        contract_uid,
        contract_product,
        data_source=requested_source or None,
    )
    if not Path(contract_file).is_file():
        raise ProductMarketDataError(
            f"合约数据不存在: {contract_uid}", 404,
        )
    try:
        price_frame = pd.read_parquet(contract_file)
    except FileNotFoundError as exc:
        raise ProductMarketDataError(
            f"合约数据不存在: {contract_uid}", 404,
        ) from exc
    if price_frame.empty:
        raise ProductMarketDataError("合约数据为空", 404)

    source_oi_column = open_interest_column(price_frame.columns)

    from tools.data.types import DataFreq

    try:
        frequency = DataFreq(str(payload.get("freq") or "MIN1"))
    except Exception:
        frequency = DataFreq("MIN1")
    if available_freqs and frequency.name not in available_freqs:
        frequency = DataFreq(available_freqs[0])
    daily = frequency.is_day_multiple()
    if daily:
        price_frame["trading_day"] = pd.to_datetime(price_frame["trading_day"])
        aggregation = {
            "open": ("open_price", "first"),
            "high": ("highest_price", "max"),
            "low": ("lowest_price", "min"),
            "close": ("close_price", "last"),
            "volume": ("volume", "sum"),
        }
        if source_oi_column:
            aggregation["open_interest"] = (source_oi_column, "last")
        price_frame = (
            price_frame.groupby("trading_day")
            .agg(**aggregation)
            .reset_index()
            .rename(columns={"trading_day": "time_idx"})
        )
        price_frame = cast(pd.DataFrame, price_frame)
        columns = ("open", "high", "low", "close", "volume")
        time_column = "time_idx"
    else:
        price_frame["trade_time"] = pd.to_datetime(price_frame["trade_time"])
        price_frame = price_frame.sort_values("trade_time")
        columns = (
            "open_price", "highest_price", "lowest_price", "close_price",
            "volume",
        )
        time_column = "trade_time"

    start = range_bound(
        payload.get("start_date"), payload.get("start_time"),
        is_end=False, precision=payload.get("time_precision"),
    )
    end = range_bound(
        payload.get("end_date"), payload.get("end_time"),
        is_end=True, precision=payload.get("time_precision"),
    )
    if start is not None:
        price_frame = price_frame[price_frame[time_column] >= start]
    if end is not None:
        price_frame = price_frame[price_frame[time_column] <= end]
    price_frame = cast(pd.DataFrame, price_frame)
    if price_frame.empty:
        raise ProductMarketDataError("指定范围内无合约价格数据", 404)

    oi_column = open_interest_column(price_frame.columns)
    has_open_interest = oi_column is not None
    timezone = getattr(contract_product, "timezone", None) or "Asia/Shanghai"
    rows = [
        format_price_row(
            row=row,
            time_col=time_column,
            o_col=columns[0],
            h_col=columns[1],
            l_col=columns[2],
            c_col=columns[3],
            v_col=columns[4],
            oi_col=oi_column,
            freq_is_daily=daily,
            timezone=timezone,
        )
        for _, row in price_frame.iterrows()
    ]
    rows, total_count = bounded_ohlcv_rows(rows, payload)
    name_parts = contract_uid.split("|")
    return {
        "success": True,
        "product": contract_uid,
        "contract_uid": contract_uid,
        "contract_name": (
            name_parts[-2] + name_parts[-1]
            if len(name_parts) > 1 else contract_uid
        ),
        "is_term_contract": True,
        "adjusted": False,
        "supports_adjusted": False,
        "supports_term_structure": False,
        "freq": frequency.name,
        "data_source": requested_source or (
            available_sources[0]["alias"] if available_sources else ""
        ),
        "available_sources": available_sources,
        "available_freqs": available_freqs,
        "count": total_count,
        "returned_count": len(rows),
        "has_oi": has_open_interest,
        "fields": (
            product_public_fields(contract_product)
            if contract_product is not None else {}
        ),
        "data": rows,
    }
