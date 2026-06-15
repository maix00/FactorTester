from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pandas as pd

from server.services import data_source_sqlite
from server.services.data_dictionary import DataSourceEntry
from tools.data.DataProviderProductTS import DataProviderProductTS as DataSource
from tools.data import _DataMultipleProviderMeta as DataSourceMeta


def test_data_source_sqlite_mirror_builds_duckdb_preview(monkeypatch, tmp_path):
    parquet_path = tmp_path / "sample.parquet"
    sqlite_path = tmp_path / "cache" / "sqlite-web" / "datasources.sqlite"

    pd.DataFrame(
        {
            "trading_day": ["2026-06-01"],
            "open_price": [1.0],
            "close_price": [2.0],
        }
    ).to_parquet(parquet_path, index=False)

    source = DataSource(
        alias="test_source",
        data_freq="DAY1",
        get_object_path=lambda _: str(parquet_path),
        if_object_is_in_source=lambda _: True,
        timezone="Asia/Shanghai",
        time_cols_mapping={"trading_day": "1day"},
        data_cols_mapping={"open_price": "OPEN", "close_price": "CLOSE"},
    )

    monkeypatch.setattr(
        data_source_sqlite,
        "DATA_SOURCE_SQLITE_DIR",
        sqlite_path.parent,
    )
    monkeypatch.setattr(
        data_source_sqlite,
        "DATA_SOURCE_SQLITE_PATH",
        sqlite_path,
    )
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
        data_source_sqlite,
        "Settings",
        SimpleNamespace(
            get_all_products=lambda: [
                SimpleNamespace(name="TEST.DCE", alias="TEST.DCE", timezone="Asia/Shanghai")
            ]
        ),
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
