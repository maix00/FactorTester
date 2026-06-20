from __future__ import annotations

import settings as Settings
from server.services import local_sql_data


def test_local_sql_registry_exposes_openctp_store(monkeypatch, tmp_path):
    monkeypatch.setattr(Settings, "CACHE_DIR", tmp_path / "localdata")
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "localdata" / "unifieddata.sqlite")

    stores = local_sql_data.list_stores()
    openctp_store = next(store for store in stores if store["key"] == "openctp")

    assert openctp_store["label"] == "统一主库 (unifieddata.sqlite)"
    assert openctp_store["database"].endswith("unifieddata.sqlite")
