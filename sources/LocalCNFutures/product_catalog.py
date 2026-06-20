"""SQLite-backed product catalog discovered from local futures data files."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from scripts.data_dir import CACHE_DB_PATH, DATA_DIR
from sources.LocalCNFutures import SOURCE_DATA_DIR
from tools.data.sqlite.db import connect_sqlite, replace_dataframe
from tools.data.artifacts.coordinator import ARTIFACT_COVERAGE_TABLE, ensure_artifact_schema
from sources.LocalCNFutures.trading_sessions import (
    infer_trading_sessions_from_parquet,
    sessions_to_record,
)


DISCOVERED_TABLE = "src_local_cnfutures_discovered_products"
SECTORS_TABLE = "src_local_cnfutures_sectors"
PRODUCTS_VIEW = "local_cnfutures_products"
OBSERVED_SESSIONS_TABLE = "src_local_cnfutures_observed_sessions"
_CONTINUOUS_ARTIFACT_KEY = "LocalCNFutures:continuous_contracts:primary_secondary"
_TERM_STRUCTURE_ARTIFACT_KEY = "LocalCNFutures:term_structure:listed_contracts"

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


def _empty_observed_sessions() -> pd.DataFrame:
    return pd.DataFrame(columns=[
        "product_name",
        "observed_day_sessions",
        "observed_night_session",
        "observed_days",
        "source_mtime_ns",
        "inferred_at",
    ])


def _load_observed_sessions(db_path: str | Path) -> pd.DataFrame:
    with connect_sqlite(db_path) as conn:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (OBSERVED_SESSIONS_TABLE,),
        ).fetchone()
        if exists is None:
            return _empty_observed_sessions()
        return pd.read_sql_query(f'SELECT * FROM "{OBSERVED_SESSIONS_TABLE}"', conn)


def infer_observed_sessions(
    *,
    data_dir: str | Path,
    discovered: pd.DataFrame,
    sectors: pd.DataFrame,
    existing: pd.DataFrame | None = None,
    product_names: set[str] | None = None,
    force: bool = False,
) -> pd.DataFrame:
    """Infer sessions for missing-metadata products, or explicitly selected products."""
    root = Path(data_dir)
    records = {
        str(row["product_name"]): dict(row)
        for _, row in (existing if existing is not None else _empty_observed_sessions()).iterrows()
    }
    sector_identities = {
        (str(row["品种代码"]).upper(), str(row["交易所代码"]).upper())
        for _, row in sectors.iterrows()
        if pd.notna(row["品种代码"]) and pd.notna(row["交易所代码"])
    }

    for _, product in discovered.iterrows():
        name = str(product["product_name"])
        explicitly_selected = product_names is not None and name in product_names
        has_sector_metadata = (
            str(product["product_code"]).upper(),
            str(product["sector_exchange_code"]).upper(),
        ) in sector_identities
        if product_names is not None and not explicitly_selected:
            continue
        if product_names is None and has_sector_metadata:
            continue

        path = root / "main_mink" / f"{name}.parquet"
        if not path.is_file():
            continue
        existing_record = records.get(name)
        if (
            not force
            and existing_record is not None
            and int(existing_record.get("source_mtime_ns") or 0) == path.stat().st_mtime_ns
        ):
            continue
        try:
            sessions = infer_trading_sessions_from_parquet(path, product_name=name)
        except (OSError, ValueError):
            continue
        records[name] = sessions_to_record(sessions)

    if not records:
        return _empty_observed_sessions()
    return pd.DataFrame(list(records.values()), columns=_empty_observed_sessions().columns)


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
            CASE WHEN cp.product_name IS NULL THEN 0 ELSE 1 END AS "_has_primary_continuous",
            CASE WHEN cs.product_name IS NULL THEN 0 ELSE 1 END AS "_has_secondary_continuous",
            CASE WHEN tc.product_name IS NULL THEN 0 ELSE 1 END AS "_has_term_structure",
            tc.start_value AS "_term_structure_start",
            tc.end_value AS "_term_structure_end",
            tc.row_count AS "_term_structure_rows",
            tc.entity_count AS "_term_structure_contracts",
            o.observed_day_sessions AS "_observed_day_sessions",
            o.observed_night_session AS "_observed_night_session",
            CASE
                WHEN s."品种代码" IS NOT NULL THEN 'sectors'
                WHEN o.product_name IS NOT NULL THEN 'observed'
                ELSE 'unknown'
            END AS "_session_source",
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
            COALESCE(s."日盘时间", o.observed_day_sessions) AS "日盘时间",
            COALESCE(s."夜盘时间", o.observed_night_session) AS "夜盘时间",
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
        LEFT JOIN "{OBSERVED_SESSIONS_TABLE}" AS o
          ON o.product_name = d.product_name
        LEFT JOIN "{ARTIFACT_COVERAGE_TABLE}" AS cp
          ON cp.artifact_key = '{_CONTINUOUS_ARTIFACT_KEY}'
         AND cp.product_name = d.product_name
         AND cp.variant = 'primary'
        LEFT JOIN "{ARTIFACT_COVERAGE_TABLE}" AS cs
          ON cs.artifact_key = '{_CONTINUOUS_ARTIFACT_KEY}'
         AND cs.product_name = d.product_name
         AND cs.variant = 'secondary'
        LEFT JOIN "{ARTIFACT_COVERAGE_TABLE}" AS tc
          ON tc.artifact_key = '{_TERM_STRUCTURE_ARTIFACT_KEY}'
         AND tc.product_name = d.product_name
         AND tc.variant = 'listed_contracts'
        ORDER BY d.product_name, s."版本"
        '''
    )


def sync_product_catalog(
    *,
    data_dir: str | Path = SOURCE_DATA_DIR,
    db_path: str | Path = CACHE_DB_PATH,
) -> str:
    """Replace source snapshots and rebuild the canonical product view."""
    ensure_artifact_schema(db_path)
    root = Path(data_dir)
    discovered = discover_products(root)
    sectors = _load_sectors(root / "sectors.csv")
    observed = infer_observed_sessions(
        data_dir=root,
        discovered=discovered,
        sectors=sectors,
        existing=_load_observed_sessions(db_path),
    )
    with connect_sqlite(db_path) as conn:
        replace_dataframe(conn, DISCOVERED_TABLE, discovered)
        replace_dataframe(conn, SECTORS_TABLE, sectors)
        replace_dataframe(conn, OBSERVED_SESSIONS_TABLE, observed)
        conn.execute(
            f'CREATE UNIQUE INDEX IF NOT EXISTS "idx_{DISCOVERED_TABLE}_name" '
            f'ON "{DISCOVERED_TABLE}" (product_name)'
        )
        conn.execute(
            f'CREATE INDEX IF NOT EXISTS "idx_{SECTORS_TABLE}_identity" '
            f'ON "{SECTORS_TABLE}" ("品种代码", "交易所代码")'
        )
        conn.execute(
            f'CREATE UNIQUE INDEX IF NOT EXISTS "idx_{OBSERVED_SESSIONS_TABLE}_name" '
            f'ON "{OBSERVED_SESSIONS_TABLE}" (product_name)'
        )
        _create_products_view(conn)
    return str(db_path)


def sync_observed_trading_sessions(
    *,
    data_dir: str | Path = SOURCE_DATA_DIR,
    db_path: str | Path = CACHE_DB_PATH,
    product_names: set[str] | None = None,
    force: bool = False,
) -> pd.DataFrame:
    """Explicitly refresh observed sessions and rebuild the canonical view."""
    ensure_artifact_schema(db_path)
    root = Path(data_dir)
    discovered = discover_products(root)
    sectors = _load_sectors(root / "sectors.csv")
    observed = infer_observed_sessions(
        data_dir=root,
        discovered=discovered,
        sectors=sectors,
        existing=_load_observed_sessions(db_path),
        product_names=product_names,
        force=force,
    )
    with connect_sqlite(db_path) as conn:
        replace_dataframe(conn, DISCOVERED_TABLE, discovered)
        replace_dataframe(conn, SECTORS_TABLE, sectors)
        replace_dataframe(conn, OBSERVED_SESSIONS_TABLE, observed)
        _create_products_view(conn)
    return observed


def load_product_catalog(
    *,
    data_dir: str | Path = SOURCE_DATA_DIR,
    db_path: str | Path = CACHE_DB_PATH,
    sync: bool = True,
) -> pd.DataFrame:
    if sync:
        sync_product_catalog(data_dir=data_dir, db_path=db_path)
    with connect_sqlite(db_path) as conn:
        return pd.read_sql_query(f'SELECT * FROM "{PRODUCTS_VIEW}"', conn)
