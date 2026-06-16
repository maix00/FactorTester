from __future__ import annotations

import sqlite3

import Settings
from server.services import data_dictionary as data_dictionary_module
from server.services.sqlite import data_dictionary as data_dictionary_sqlite


def test_data_dictionary_sqlite_store_roundtrip(monkeypatch, tmp_path):
    sqlite_path = tmp_path / "cache" / "localdata" / "unifieddata.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DIR", sqlite_path.parent)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", sqlite_path)

    sample = data_dictionary_module.DataDictionary(
        generated_at="2026-06-16 10:00:00",
        data_columns=[
            data_dictionary_module.DataColumnEntry(name="OPEN", code="O", description="开盘价"),
        ],
        frequency_types=[{"name": "MIN1", "value": "0 days 00:01:00", "alias": "1min"}],
        data_sources=[
            data_dictionary_module.DataSourceEntry(
                alias="test_source",
                freq="DAY1",
                timezone="Asia/Shanghai",
                columns_count=1,
                columns_list="open→OPEN",
            )
        ],
        param_types=[
            data_dictionary_module.ParamTypeEntry(
                name="WindowParam",
                alias="$W",
                description="窗口参数",
                default_example="1",
            )
        ],
        factors=[
            data_dictionary_module.FactorEntry(
                name="MmRet",
                desc="收益率动量",
                description="示例因子",
                math_expr="x",
                category="Mm",
                source_file="Factors/MmRet.py",
                params=[
                    data_dictionary_module.ParamEntry(
                        alias="$N",
                        type="WindowParam",
                        default_value="20",
                        description="窗口",
                    )
                ],
            )
        ],
        settings=[
            data_dictionary_module.SettingEntry(
                name="CACHE_DB_PATH",
                value="unifieddata.sqlite",
                description="统一主库路径",
            )
        ],
        factor_categories={"Mm": "动量因子"},
    )

    monkeypatch.setattr(
        data_dictionary_module,
        "build_data_dictionary",
        lambda: sample,
    )

    path = data_dictionary_sqlite.ensure_data_dictionary_sqlite_store()
    assert path == str(sqlite_path)
    assert sqlite_path.exists()

    snapshot = data_dictionary_sqlite.load_data_dictionary_snapshot()
    assert snapshot is not None
    assert snapshot["generated_at"] == "2026-06-16 10:00:00"
    assert snapshot["data_columns"][0]["name"] == "OPEN"
    assert snapshot["factors"][0]["params"][0]["alias"] == "$N"

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
        assert "data_dictionary_meta" in tables
        assert "data_dictionary_factors" in tables
        assert conn.execute("SELECT COUNT(*) AS n FROM data_dictionary_factors").fetchone()["n"] == 1
