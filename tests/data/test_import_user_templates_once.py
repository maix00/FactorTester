from __future__ import annotations

import json

import Settings
from scripts.import_user_templates_once import import_user_templates_once
from tools.data.account_manage import load_user_templates


def _write_templates(path, templates):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"templates": templates}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_import_user_templates_once_maps_legacy_layout_to_sqlite(monkeypatch, tmp_path):
    db_path = tmp_path / "unifieddata.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", db_path)

    root = tmp_path / "users"
    user_dir = root / "default$alice@1"
    _write_templates(user_dir / "time_templates.json", [{"id": "t1", "name": "time"}])
    _write_templates(user_dir / "params_templates" / "MmRet.json", [{"id": "p1", "name": "params"}])
    _write_templates(user_dir / "global_templates" / "MmRet.json", [{"id": "g1", "name": "global"}])
    _write_templates(user_dir / "group_settings_templates" / "snapshots" / "MmRet.json", [{"id": "s1", "name": "snapshot"}])

    result = import_user_templates_once(str(root))

    assert result["users"] == 1
    assert result["collections"] == 4
    assert result["templates"] == 4
    assert load_user_templates("default$alice@1", "time") == [{"id": "t1", "name": "time"}]
    assert load_user_templates("default$alice@1", "params", ff_alias="MmRet") == [{"id": "p1", "name": "params"}]
    assert load_user_templates("default$alice@1", "global", scope_key="MmRet") == [{"id": "g1", "name": "global"}]
    assert load_user_templates("default$alice@1", "group_settings", ff_alias="MmRet", scope_key="snapshots") == [{"id": "s1", "name": "snapshot"}]
