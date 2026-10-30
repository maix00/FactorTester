from __future__ import annotations

import json

import settings as Settings
from scripts.import_local_research_metadata_once import (
    import_local_research_metadata_once,
    verify_local_research_metadata_import,
)
from tools.data.account_manage import (
    list_factor_param_config_scopes,
    load_factor_param_config,
    load_product_groups,
)


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_import_preserves_research_metadata_without_importing_identity(
    monkeypatch, tmp_path,
):
    db_path = tmp_path / "cache.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", db_path)

    root = tmp_path / "users"
    principal = root / "default$alice@1"
    _write_json(root / "accounts.json", [{"username": "alice", "password": "ignored"}])
    _write_json(
        principal / "product_groups.json",
        [{"name": "黑色", "paths": ["单因子测试/黑色"], "updated_at": "2026-06-17 12:00:00"}],
    )
    _write_json(
        principal / "factor_library_param_configs" / "中国期货日盘" / "MmRet.json",
        {
            "id": "default$alice@1",
            "scope": "user_product_group",
            "scope_key": "中国期货日盘",
            "product_group": "中国期货日盘",
            "scope_user_id": "default$alice@1",
            "name": "default$alice@1",
            "params_list": [{"window": 5}],
            "updated_at": "2026-06-17 12:00:01",
        },
    )

    result = import_local_research_metadata_once(root)

    assert result["principals"] == 1
    assert result["identity_records_imported"] == 0
    assert result["product_groups"] == 1
    assert result["param_scopes"] == 1
    assert result["param_configs"] == 1
    assert load_product_groups("default$alice@1")[0]["name"] == "黑色"
    assert list_factor_param_config_scopes("default$alice@1") == ["中国期货日盘"]
    assert load_factor_param_config(
        "default$alice@1", "MmRet", "中国期货日盘",
    )["params_list"] == [{"window": 5}]
    assert verify_local_research_metadata_import(root)["mismatches"] == []
