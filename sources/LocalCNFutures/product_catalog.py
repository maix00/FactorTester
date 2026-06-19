"""SQLite-backed product catalog discovered from local futures data files."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from scripts.data_dir import CACHE_DB_PATH, DATA_DIR
from tools.data.sqlite.db import connect_sqlite, replace_dataframe


DISCOVERED_TABLE = "src_local_cnfutures_discovered_products"
SECTORS_TABLE = "src_local_cnfutures_sectors"
PRODUCTS_VIEW = "local_cnfutures_products"

_EXCHANGE_TO_SECTOR_CODE = {
    "DCE": "DCE",
    "CZC": "CZCE",
    "INE": "INE",
    "SHF": "SHFE",
    "CFE": "CFFEX",
    "GFE": "GFEX",
}

_SECTOR_COLUMNS = (
    "交易所",
    "交易所代码",
    "简称",
    "合约标的",
    "类别",
    "品种代码",
    "版本",
    "最高版本",
    "变动后代码",
    "代码注",
    "集合竞价",
    "日盘时间",
    "夜盘时间",
    "合约乘数",
    "最小跳动",
    "标准合约上市日",
    "夜盘交易开始日",
    "标准合约终止交易日",
    "数据更新时间",
)


def _main_product_names(folder: Path) -> set[str]:
    if not folder.is_dir():
        return set()
    result = set()
    for path in folder.glob("*.parquet"):
        stem = path.stem
        if "." not in stem:
            continue
        product_code, _ = stem.rsplit(".", 1)
        if product_code.endswith("_S") or product_code.endswith("-S"):
            continue
        result.add(stem)
    return result


def _wind_product_names(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    frame = pd.read_parquet(path, columns=["S_INFO_WINDCODE"])
    return {
        str(value).strip()
        for value in frame["S_INFO_WINDCODE"].dropna().unique()
        if "." in str(value)
    }


def discover_products(data_dir: str | Path) -> pd.DataFrame:
    """Discover main products from actual MIN1/DAY1 parquet inventories."""
    root = Path(data_dir)
    min1_names = _main_product_names(root / "main_mink")
    day1_names = _main_product_names(root / "main_dayk")
    wind_names = _wind_product_names(root / "wind_mapping.parquet")

    rows = []
    for product_name in sorted(min1_names | day1_names):
        product_code, exchange_short = product_name.rsplit(".", 1)
        rows.append(
            {
                "product_name": product_name,
                "product_code": product_code.upper(),
                "exchange_short": exchange_short.upper(),
                "sector_exchange_code": _EXCHANGE_TO_SECTOR_CODE.get(
                    exchange_short.upper(), exchange_short.upper()
                ),
                "has_min1": int(product_name in min1_names),
                "has_day1": int(product_name in day1_names),
                "has_wind_mapping": int(product_name in wind_names),
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "product_name",
            "product_code",
            "exchange_short",
            "sector_exchange_code",
            "has_min1",
            "has_day1",
            "has_wind_mapping",
        ],
    )


def _load_sectors(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame(columns=_SECTOR_COLUMNS)
    frame = pd.read_csv(path)
    missing = set(_SECTOR_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"sectors.csv 缺少字段: {sorted(missing)}")
    return frame.loc[:, list(_SECTOR_COLUMNS)]


def _create_products_view(conn: sqlite3.Connection) -> None:
    conn.execute(f'DROP VIEW IF EXISTS "{PRODUCTS_VIEW}"')
    conn.execute(
        f'''
        CREATE VIEW "{PRODUCTS_VIEW}" AS
        SELECT
            d.product_name AS "_product_name",
            d.has_min1 AS "_has_min1",
            d.has_day1 AS "_has_day1",
            d.has_wind_mapping AS "_has_wind_mapping",
            COALESCE(s."交易所", d.sector_exchange_code) AS "交易所",
            COALESCE(s."交易所代码", d.sector_exchange_code) AS "交易所代码",
            s."简称" AS "简称",
            s."合约标的" AS "合约标的",
            s."类别" AS "类别",
            COALESCE(s."品种代码", d.product_code) AS "品种代码",
            s."版本" AS "版本",
            s."最高版本" AS "最高版本",
            s."变动后代码" AS "变动后代码",
            s."代码注" AS "代码注",
            s."集合竞价" AS "集合竞价",
            s."日盘时间" AS "日盘时间",
            s."夜盘时间" AS "夜盘时间",
            s."合约乘数" AS "合约乘数",
            s."最小跳动" AS "最小跳动",
            s."标准合约上市日" AS "标准合约上市日",
            s."夜盘交易开始日" AS "夜盘交易开始日",
            s."标准合约终止交易日" AS "标准合约终止交易日",
            s."数据更新时间" AS "数据更新时间"
        FROM "{DISCOVERED_TABLE}" AS d
        LEFT JOIN "{SECTORS_TABLE}" AS s
          ON UPPER(TRIM(s."品种代码")) = d.product_code
         AND UPPER(TRIM(s."交易所代码")) = d.sector_exchange_code
        ORDER BY d.product_name, s."版本"
        '''
    )


def sync_product_catalog(
    *,
    data_dir: str | Path = DATA_DIR,
    db_path: str | Path = CACHE_DB_PATH,
) -> str:
    """Replace source snapshots and rebuild the canonical product view."""
    root = Path(data_dir)
    discovered = discover_products(root)
    sectors = _load_sectors(root / "sectors.csv")
    with connect_sqlite(db_path) as conn:
        replace_dataframe(conn, DISCOVERED_TABLE, discovered)
        replace_dataframe(conn, SECTORS_TABLE, sectors)
        conn.execute(
            f'CREATE UNIQUE INDEX IF NOT EXISTS "idx_{DISCOVERED_TABLE}_name" '
            f'ON "{DISCOVERED_TABLE}" (product_name)'
        )
        conn.execute(
            f'CREATE INDEX IF NOT EXISTS "idx_{SECTORS_TABLE}_identity" '
            f'ON "{SECTORS_TABLE}" ("品种代码", "交易所代码")'
        )
        _create_products_view(conn)
    return str(db_path)


def load_product_catalog(
    *,
    data_dir: str | Path = DATA_DIR,
    db_path: str | Path = CACHE_DB_PATH,
    sync: bool = True,
) -> pd.DataFrame:
    if sync:
        sync_product_catalog(data_dir=data_dir, db_path=db_path)
    with connect_sqlite(db_path) as conn:
        return pd.read_sql_query(f'SELECT * FROM "{PRODUCTS_VIEW}"', conn)
