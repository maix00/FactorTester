from __future__ import annotations

from server.services import local_sql_data
from sources.OpenCTP import client as openctp_client


def test_local_sql_registry_exposes_openctp_store(monkeypatch, tmp_path):
    monkeypatch.setattr(openctp_client, "CACHE_DIR", tmp_path / "openctp")
    monkeypatch.setattr(openctp_client, "CACHE_DB_PATH", tmp_path / "openctp" / "openctp.sqlite")

    stores = local_sql_data.list_stores()
    openctp_store = next(store for store in stores if store["key"] == "openctp")

    assert openctp_store["label"] == "OpenCTP 字段数据"
    assert openctp_store["database"].endswith("openctp.sqlite")
