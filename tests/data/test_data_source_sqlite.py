from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pandas as pd

import Settings
from tools.data.sqlite import data_source as data_source_sqlite
from tools.data.datadict_scan import DataSourceEntry
from tools.data import DataProviderProductTS as DataSource
from tools.data import _DataMultipleProviderMeta as DataSourceMeta


def test_data_source_sqlite_mirror_builds_duckdb_preview(monkeypatch, tmp_path):
    parquet_path = tmp_path / "sample.parquet"
    sqlite_path = tmp_path / "cache" / "localdata" / "unifieddata.sqlite"

    pd.DataFrame(
        {
            "trading_day": ["2026-06-01"],
            "open_price": [1.0],
            "close_price": [2.0],
        }
    ).to_parquet(parquet_path, index=False)

    source = DataSource(
        key="test_source",
        alias="test_source",
        data_freq="DAY1",
        get_object_path=lambda _: str(parquet_path),
        if_object_is_in_source=lambda _: True,
        timezone="Asia/Shanghai",
        time_cols_mapping={"trading_day": "1day"},
        data_cols_mapping={"open_price": "OPEN", "close_price": "CLOSE"},
    )

    monkeypatch.setattr(Settings, "CACHE_DIR", sqlite_path.parent)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", sqlite_path)
    monkeypatch.setattr(
        data_source_sqlite,
        "scan_data_sources",
        lambda: [
            DataSourceEntry(
                alias="test_source",
                freq="DAY1",
                timezone="Asia/Shanghai",
                columns_count=2,
                columns_list="open_price→OPEN, close_price→CLOSE",
            )
        ],
    )
    monkeypatch.setattr(
        Settings,
        "get_all_products",
        lambda: [SimpleNamespace(name="TEST.DCE", alias="TEST.DCE", timezone="Asia/Shanghai")],
    )
    monkeypatch.setattr(
        DataSourceMeta,
        "_sources_registry",
        {DataSource: {"test_source": source}},
        raising=False,
    )

    path = data_source_sqlite.ensure_data_source_sqlite_store()
    assert path == str(sqlite_path)
    assert sqlite_path.exists()

    with sqlite3.connect(sqlite_path) as conn:
        conn.row_factory = sqlite3.Row
        tables = {
            row["name"]
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                """
            ).fetchall()
        }
        assert "data_sources" in tables
        assert "data_source_products" in tables
        assert "data_source_previews" in tables
        preview_tables = [name for name in tables if name.startswith("preview__")]
        assert preview_tables
        preview_rows = conn.execute(f'SELECT * FROM "{preview_tables[0]}"').fetchall()
        assert len(preview_rows) == 1
        assert preview_rows[0]["__source__"] == "test_source"
        assert preview_rows[0]["open_price"] == 1.0


def test_data_provider_product_ts_selects_available_source(monkeypatch, tmp_path):
    parquet_path = tmp_path / "sample.parquet"
    pd.DataFrame(
        {
            "trading_day": ["2026-06-01"],
            "open_price": [1.0],
            "close_price": [2.0],
        }
    ).to_parquet(parquet_path, index=False)

    source = DataSource(
        key="test_source",
        alias="test_source",
        data_freq="DAY1",
        get_object_path=lambda _: str(parquet_path),
        if_object_is_in_source=lambda _: True,
        timezone="Asia/Shanghai",
        time_cols_mapping={"trading_day": "1day"},
        data_cols_mapping={"open_price": "OPEN", "close_price": "CLOSE"},
    )
    product = SimpleNamespace(name="TEST.DCE", alias="TEST.DCE", timezone="Asia/Shanghai")

    monkeypatch.setattr(
        DataSourceMeta,
        "_sources_registry",
        {DataSource: {"test_source": source}},
        raising=False,
    )

    available = DataSource.available_for_product(product, "DAY1")
    assert available == [source]
    assert DataSource.select_for_product(product, "DAY1") is source
    assert DataSource.select_for_product(product, "DAY1", source=source) is source
