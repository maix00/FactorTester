from __future__ import annotations

import sqlite3

import Settings
from server.services import factor_metadata_sqlite
from server.services import accounts as account_store


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
            'SELECT source_kind, owner_username, factor_id, factor_name FROM factor_catalog ORDER BY source_kind, owner_username, factor_id'
        ).fetchall()
        assert [(row["source_kind"], row["owner_username"], row["factor_id"], row["factor_name"]) for row in catalog] == [
            ("custom", "default$alice@1", "default$alice@1_Custom", "CustomFactor"),
            ("public", "", "MmRet", "MmRet"),
        ]

        params = conn.execute(
            'SELECT source_kind, owner_username, factor_id, param_index, alias FROM factor_catalog_params'
        ).fetchall()
        assert [(row["source_kind"], row["owner_username"], row["factor_id"], row["param_index"], row["alias"]) for row in params] == [
            ("public", "", "MmRet", 0, "$N"),
        ]
