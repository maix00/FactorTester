"""File-backed Tiger historical cache exposed to FactorTester backtests."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from settings import DATA_DIR
from tools.data.providers import (
    DataProviderProductTS,
    DataProviderProductTSBundle,
)
from tools.data.types import DataColumn, DataFreq

from .products import JPFutures


CACHE_ENV = "FACTORTESTER_TIGER_CACHE_DIR"

_DATA_COLUMNS = {
    "open_price": DataColumn.OPEN,
    "highest_price": DataColumn.HIGH,
    "lowest_price": DataColumn.LOW,
    "close_price": DataColumn.CLOSE,
    "volume": DataColumn.VOLUME,
    "turnover": DataColumn.TURNOVER,
    "open_interest": DataColumn.OPEN_INTEREST,
    "settlement_price": DataColumn.SETTLEMENT_PRICE,
}


def tiger_cache_root() -> Path:
    configured = os.environ.get(CACHE_ENV, "").strip()
    return (
        Path(configured).expanduser()
        if configured
        else Path(DATA_DIR) / "Tiger" / "market_data"
    )


def tiger_cache_path(product: Any, frequency: DataFreq | str) -> str:
    freq = DataFreq(frequency)
    identifier = str(getattr(product, "tiger_identifier", "")).strip()
    if not identifier:
        return ""
    return str(tiger_cache_root() / "OSE" / freq.name / f"{identifier}.parquet")


def _is_jp_futures(product: Any) -> bool:
    return isinstance(product, JPFutures)


TIGER_OSE_MIN1 = DataProviderProductTS(
    key="TigerOSEFuturesMIN1",
    data_freq=DataFreq.MIN1,
    get_object_path=lambda product: tiger_cache_path(product, DataFreq.MIN1),
    if_object_is_in_source=lambda product: (
        _is_jp_futures(product)
        and DataProviderProductTS._path_has_rows(
            tiger_cache_path(product, DataFreq.MIN1)
        )
    ),
    timezone="Asia/Tokyo",
    time_cols_mapping={"trade_time": DataFreq.MIN1, "trading_day": DataFreq.DAY1},
    data_cols_mapping=_DATA_COLUMNS,
)

TIGER_OSE_DAY1 = DataProviderProductTS(
    key="TigerOSEFuturesDAY1",
    data_freq=DataFreq.DAY1,
    get_object_path=lambda product: tiger_cache_path(product, DataFreq.DAY1),
    if_object_is_in_source=lambda product: (
        _is_jp_futures(product)
        and DataProviderProductTS._path_has_rows(
            tiger_cache_path(product, DataFreq.DAY1)
        )
    ),
    timezone="Asia/Tokyo",
    time_cols_mapping={"trading_day": DataFreq.DAY1},
    data_cols_mapping=_DATA_COLUMNS,
)

TIGER = DataProviderProductTSBundle(
    key="Tiger",
    label="Tiger",
    members=(TIGER_OSE_MIN1, TIGER_OSE_DAY1),
)
