from pathlib import Path
import sqlite3

import pandas as pd

from sources.LocalCNFutures.product_catalog import (
    DISCOVERED_TABLE,
    PRODUCTS_VIEW,
    SECTORS_TABLE,
    load_product_catalog,
    sync_product_catalog,
)


SECTOR_COLUMNS = [
    "交易所", "交易所代码", "简称", "合约标的", "类别", "品种代码", "版本",
    "最高版本", "变动后代码", "代码注", "集合竞价", "日盘时间", "夜盘时间",
    "合约乘数", "最小跳动", "标准合约上市日", "夜盘交易开始日",
    "标准合约终止交易日", "数据更新时间",
]


def _build_data_dir(root: Path) -> None:
    (root / "main_mink").mkdir()
    (root / "main_dayk").mkdir()
    (root / "main_mink" / "BZ.DCE.parquet").touch()
    (root / "main_dayk" / "BZ.DCE.parquet").touch()
    (root / "main_mink" / "A.DCE.parquet").touch()
    (root / "main_mink" / "A_S.DCE.parquet").touch()
    pd.DataFrame(
        {"S_INFO_WINDCODE": ["BZ.DCE", "A.DCE", "WIND_ONLY.DCE"]}
    ).to_parquet(root / "wind_mapping.parquet")
    pd.DataFrame(
        [["大连商品交易所", "DCE", "豆一", "豆一", "农产品", "A", "1", "1",
          None, None, None, "09:00-15:00", None, 10, 1, None, None, None, None]],
        columns=SECTOR_COLUMNS,
    ).to_csv(root / "sectors.csv", index=False)


def test_catalog_keeps_data_product_without_sector_metadata(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _build_data_dir(data_dir)
    db_path = tmp_path / "catalog.sqlite"

    catalog = load_product_catalog(data_dir=data_dir, db_path=db_path)

    bz = catalog[catalog["_product_name"] == "BZ.DCE"].iloc[0]
    assert bz["品种代码"] == "BZ"
    assert bz["交易所代码"] == "DCE"
    assert bz["_has_min1"] == 1
    assert bz["_has_day1"] == 1
    assert pd.isna(bz["类别"])
    assert "WIND_ONLY.DCE" not in set(catalog["_product_name"])


def test_catalog_sync_is_idempotent_and_sectors_are_stored(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _build_data_dir(data_dir)
    db_path = tmp_path / "catalog.sqlite"

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

    assert discovered_count == 2
    assert sectors_count == 1
    assert products_count == 2
