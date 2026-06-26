from __future__ import annotations

import json

import settings as Settings
from scripts.import_user_account_data_once import (
    import_user_account_data_once,
    verify_user_account_data_import,
)
from tools.data.account_manage import (
    list_factor_param_config_scopes,
    load_factor_param_config,
    load_product_groups,
    load_user_templates,
)


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_import_user_account_data_once_preserves_templates_groups_and_param_configs(monkeypatch, tmp_path):
    db_path = tmp_path / "cache.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", db_path)

    root = tmp_path / "users"
    user_dir = root / "default$alice@1"
    _write_json(user_dir / "time_templates.json", {"templates": [{"id": "t1", "name": "time"}]})
    _write_json(user_dir / "params_templates" / "MmRet.json", {"templates": [{"id": "p1", "name": "params"}]})
    _write_json(
        user_dir / "product_groups.json",
        [{"name": "黑色", "paths": ["单因子测试/黑色"], "updated_at": "2026-06-17 12:00:00"}],
    )
    _write_json(
        user_dir / "factor_library_param_configs" / "中国期货日盘" / "MmRet.json",
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

    result = import_user_account_data_once(str(root))

    assert result["users"] == 1
    assert result["template_collections"] == 2
    assert result["templates"] == 2
    assert result["product_groups"] == 1
    assert result["param_scopes"] == 1
    assert result["param_configs"] == 1
    assert load_user_templates("default$alice@1", "time") == [{"id": "t1", "name": "time"}]
    assert load_user_templates("default$alice@1", "params", ff_alias="MmRet") == [{"id": "p1", "name": "params"}]
    assert load_product_groups("default$alice@1") == [
        {"name": "黑色", "paths": ["单因子测试/黑色"], "updated_at": "2026-06-17 12:00:00"}
    ]
    assert list_factor_param_config_scopes("default$alice@1") == ["中国期货日盘"]
    assert load_factor_param_config("default$alice@1", "MmRet", "中国期货日盘") == {
        "id": "default$alice@1",
        "scope": "user_product_group",
        "scope_key": "中国期货日盘",
        "product_group": "中国期货日盘",
        "scope_user_id": "default$alice@1",
        "name": "default$alice@1",
        "params_list": [{"window": 5}],
        "updated_at": "2026-06-17 12:00:01",
    }
    assert verify_user_account_data_import(str(root))["mismatches"] == []
