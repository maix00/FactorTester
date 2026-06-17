from __future__ import annotations

import sqlite3

import Settings
from tools.data.sqlite import factor_metadata as factor_metadata_sqlite
from tools.data.sqlite import factor_source_store
from tools.data import accounts_store as account_store


def test_factor_metadata_sqlite_store_syncs_public_and_custom_factors(monkeypatch, tmp_path):
    sqlite_path = tmp_path / "cache" / "localdata" / "unifieddata.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DIR", sqlite_path.parent)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", sqlite_path)

    monkeypatch.setattr(
        factor_metadata_sqlite,
        "_load_public_factors",
        lambda: [
            {
                "id": "MmRet",
                "name": "MmRet",
                "factor_family": "MmRet",
                "chinese_name": "收益率动量",
                "description": "示例公共因子",
                "math_expr": "x",
                "source_code": "class MmRet(FactorFamily):\n    pass\n",
                "category": "Mm",
                "source_file": "Factors/MmRet.py",
                "is_public": True,
                "params": [
                    {"alias": "$N", "type": "WindowParam", "default_value": "20", "description": "窗口"},
                ],
            }
        ],
    )
    monkeypatch.setattr(
        factor_metadata_sqlite,
        "_load_custom_factors",
        lambda username: [
            {
                "id": f"{username}_Custom",
                "name": "CustomFactor",
                "factor_family": "FactorFamily",
                "chinese_name": "自定义",
                "description": "示例自定义因子",
                "math_expr": "y",
                "source_code": "class CustomFactor(FactorFamily):\n    pass\n",
                "category": "自编",
                "is_public": False,
                "params": [],
            }
        ],
    )
    monkeypatch.setattr(
        account_store,
        "load_accounts",
        lambda: [
            {
                "username": "default$alice@1",
                "alias": "alice",
                "organization_id": "default",
                "organization_name": "默认机构",
            }
        ],
    )
    monkeypatch.setattr(
        account_store,
        "account_display_name",
        lambda account: account.get("alias") or account.get("username") or "",
    )

    path = factor_metadata_sqlite.ensure_factor_metadata_sqlite_store()
    assert path == str(sqlite_path)
    assert sqlite_path.exists()

    with sqlite3.connect(sqlite_path) as conn:
        conn.row_factory = sqlite3.Row
        catalog = conn.execute(
            'SELECT source_kind, owner_username, factor_id, factor_name, factor_family FROM factor_family_catalog ORDER BY source_kind, owner_username, factor_id'
        ).fetchall()
        assert [(row["source_kind"], row["owner_username"], row["factor_id"], row["factor_name"], row["factor_family"]) for row in catalog] == [
            ("custom", "default$alice@1", "default$alice@1_Custom", "CustomFactor", "FactorFamily"),
            ("public", "", "MmRet", "MmRet", "MmRet"),
        ]

        params = conn.execute(
            'SELECT source_kind, owner_username, factor_id, param_index, alias FROM factor_family_catalog_params'
        ).fetchall()
        assert [(row["source_kind"], row["owner_username"], row["factor_id"], row["param_index"], row["alias"]) for row in params] == [
            ("public", "", "MmRet", 0, "$N"),
        ]


def test_factor_metadata_loads_sources_before_opening_write_connection(monkeypatch, tmp_path):
    sqlite_path = tmp_path / "cache" / "localdata" / "unifieddata.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DIR", sqlite_path.parent)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", sqlite_path)

    factor_source_store.upsert_factor_source(
        "public",
        "",
        "DbPublicFactor",
        "DbPublicFactor",
        "class DbPublicFactor(FactorFamily):\n    pass\n",
    )

    def _load_public_from_source_store():
        rows = factor_source_store.list_factor_sources("public")
        return [
            {
                "id": row["factor_id"],
                "name": row["factor_name"],
                "factor_family": "FactorFamily",
                "chinese_name": "",
                "description": "",
                "math_expr": "",
                "source_code": row["source_code"],
                "category": "公共",
                "source_file": "",
                "is_public": True,
                "params": [],
            }
            for row in rows
        ]

    monkeypatch.setattr(factor_metadata_sqlite, "_load_public_factors", _load_public_from_source_store)
    monkeypatch.setattr(factor_metadata_sqlite, "_load_custom_factors", lambda username: [])
    monkeypatch.setattr(account_store, "load_accounts", lambda: [])

    path = factor_metadata_sqlite.ensure_factor_metadata_sqlite_store()
    assert path == str(sqlite_path)
