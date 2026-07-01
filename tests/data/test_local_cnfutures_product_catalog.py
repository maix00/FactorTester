from pathlib import Path
import sqlite3

import pandas as pd

from sources.LocalCNFutures.product_catalog import (
    DISCOVERED_TABLE,
    PRODUCTS_VIEW,
    SECTORS_TABLE,
    OBSERVED_SESSIONS_TABLE,
    load_product_catalog,
    sync_product_catalog,
)
from tools.data.artifacts.coordinator import ARTIFACT_COVERAGE_TABLE, ensure_artifact_schema


SECTOR_COLUMNS = [
    "交易所", "交易所代码", "简称", "合约标的", "类别", "品种代码", "版本",
    "最高版本", "变动后代码", "代码注", "集合竞价", "日盘时间", "夜盘时间",
    "合约乘数", "最小跳动", "标准合约上市日", "夜盘交易开始日",
    "标准合约终止交易日", "数据更新时间",
]


def _build_data_dir(root: Path) -> pd.DataFrame:
    (root / "main_mink").mkdir()
    (root / "main_dayk").mkdir()
    minute_rows = []
    for day in pd.date_range("2026-01-05", periods=2, freq="B"):
        for start, end in [("09:00", "10:15"), ("10:30", "11:30"), ("13:30", "15:00"), ("21:00", "23:00")]:
            minute_rows.extend(
                {"trade_time": ts, "trading_day": day}
                for ts in pd.date_range(
                    pd.Timestamp(f"{day.date()} {start}") + pd.Timedelta(minutes=1),
                    pd.Timestamp(f"{day.date()} {end}"),
                    freq="1min",
                )
            )
    pd.DataFrame(minute_rows).to_parquet(root / "main_mink" / "BZ.DCE.parquet", index=False)
    (root / "main_dayk" / "BZ.DCE.parquet").touch()
    (root / "main_mink" / "A.DCE.parquet").touch()
    (root / "main_mink" / "A_S.DCE.parquet").touch()
    pd.DataFrame(
        {"S_INFO_WINDCODE": ["BZ.DCE", "A.DCE", "WIND_ONLY.DCE"]}
    ).to_parquet(root / "wind_mapping.parquet")
    return pd.DataFrame(
        [["大连商品交易所", "DCE", "豆一", "豆一", "农产品", "A", "1", "1",
          None, None, None, "09:00-15:00", None, 10, 1, None, None, None, None]],
        columns=SECTOR_COLUMNS,
    )


def _seed_sector_db(db_path: Path, sectors: pd.DataFrame) -> None:
    with sqlite3.connect(db_path) as conn:
        sectors.to_sql(SECTORS_TABLE, conn, if_exists="replace", index=False)


def test_catalog_keeps_data_product_without_sector_metadata(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    sectors = _build_data_dir(data_dir)
    db_path = tmp_path / "catalog.sqlite"

    _seed_sector_db(db_path, sectors)
    sync_product_catalog(data_dir=data_dir, db_path=db_path)
    catalog = load_product_catalog(data_dir=data_dir, db_path=db_path)

    bz = catalog[catalog["_product_name"] == "BZ.DCE"].iloc[0]
    assert bz["品种代码"] == "BZ"
    assert bz["交易所代码"] == "DCE"
    assert bz["_has_min1"] == 1
    assert bz["_has_day1"] == 1
    assert pd.isna(bz["类别"])
    assert bz["日盘时间"] == "09:00-10:15, 10:30-11:30, 13:30-15:00"
    assert bz["夜盘时间"] == "21:00-23:00"
    assert bz["_session_source"] == "observed"
    assert "WIND_ONLY.DCE" not in set(catalog["_product_name"])


def test_catalog_sync_is_idempotent_and_sectors_are_stored(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    sectors = _build_data_dir(data_dir)
    db_path = tmp_path / "catalog.sqlite"

    _seed_sector_db(db_path, sectors)
    sync_product_catalog(data_dir=data_dir, db_path=db_path)
    sync_product_catalog(data_dir=data_dir, db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        discovered_count = conn.execute(
            f'SELECT COUNT(*) FROM "{DISCOVERED_TABLE}"'
        ).fetchone()[0]
        sectors_count = conn.execute(
            f'SELECT COUNT(*) FROM "{SECTORS_TABLE}"'
        ).fetchone()[0]
        products_count = conn.execute(
            f'SELECT COUNT(*) FROM "{PRODUCTS_VIEW}"'
        ).fetchone()[0]
        observed_count = conn.execute(
            f'SELECT COUNT(*) FROM "{OBSERVED_SESSIONS_TABLE}"'
        ).fetchone()[0]

    assert discovered_count == 2
    assert sectors_count == 1
    assert products_count == 2
    assert observed_count == 1


def test_catalog_exposes_continuous_and_curve_variants_from_artifact_coverage(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    sectors = _build_data_dir(data_dir)
    db_path = tmp_path / "catalog.sqlite"
    ensure_artifact_schema(db_path)
    _seed_sector_db(db_path, sectors)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            f'''INSERT INTO "{ARTIFACT_COVERAGE_TABLE}" (
                artifact_key, product_name, variant, start_value, end_value, row_count, entity_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?)''',
            [
                ("LocalCNFutures:continuous_contracts:primary_secondary", "BZ.DCE", "primary", None, None, 3, 2),
                ("LocalCNFutures:continuous_contracts:primary_secondary", "BZ.DCE", "secondary", None, None, 2, 2),
                ("LocalCNFutures:term_structure:listed_contracts", "BZ.DCE", "listed_contracts", "2025-01-01", "2026-01-01", 20, 5),
            ],
        )

    sync_product_catalog(data_dir=data_dir, db_path=db_path)
    catalog = load_product_catalog(data_dir=data_dir, db_path=db_path)
    bz = catalog[catalog["_product_name"] == "BZ.DCE"].iloc[0]

    assert bz["_has_primary_continuous"] == 1
    assert bz["_has_secondary_continuous"] == 1
    assert bz["_has_term_structure"] == 1
    assert bz["_term_structure_contracts"] == 5
