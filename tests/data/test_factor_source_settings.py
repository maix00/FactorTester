from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import Settings
from server.services.sqlite import factor_source_settings as factor_source_settings_sqlite


def _load_storage_module():
    storage_path = Path(__file__).resolve().parents[2] / "server" / "modules" / "custom_factors" / "storage.py"
    spec = importlib.util.spec_from_file_location("test_factor_storage_module", storage_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_factor_source_root_roundtrip_and_resolution(monkeypatch, tmp_path):
    sqlite_path = tmp_path / "cache" / "localdata" / "unifieddata.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DIR", sqlite_path.parent)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", sqlite_path)
    fallback_root = tmp_path / "fallback-user-root"
    factor_storage = _load_storage_module()
    monkeypatch.setattr(factor_storage, "user_data_dir", lambda username: str(fallback_root / username))

    username = "default$alice@1"
    custom_root = tmp_path / "alice-factor-root"

    assert factor_source_settings_sqlite.load_factor_source_root(username) is None

    saved_path = factor_source_settings_sqlite.save_factor_source_root(username, str(custom_root))
    assert saved_path == str(sqlite_path)
    assert factor_source_settings_sqlite.load_factor_source_root(username) == os.path.abspath(str(custom_root))

    resolved_dir = factor_storage.custom_factor_dir(username)
    assert resolved_dir == os.path.join(os.path.abspath(str(custom_root)), "custom_factors")

    factor_source_settings_sqlite.save_factor_source_root(username, "")
    assert factor_source_settings_sqlite.load_factor_source_root(username) is None
    assert factor_storage.custom_factor_dir(username) == os.path.join(str(fallback_root / username), "custom_factors")
