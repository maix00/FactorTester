from __future__ import annotations

import settings as Settings
from tools.data.sqlite import bootstrap as unified_sqlite


def test_unified_sqlite_bootstrap_calls_all_mirrors(monkeypatch, tmp_path):
    sqlite_path = tmp_path / "cache" / "localdata" / "unifieddata.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DIR", sqlite_path.parent)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", sqlite_path)

    calls: list[str] = []

    monkeypatch.setattr(
        "tools.data.sqlite.data_source.ensure_data_source_sqlite_store",
        lambda: calls.append("data_source") or str(sqlite_path),
    )
    monkeypatch.setattr(
        "tools.data.sqlite.account_manager.ensure_account_manager_sqlite_store",
        lambda: calls.append("users") or str(sqlite_path),
    )
    monkeypatch.setattr(
        "tools.data.sqlite.factor_metadata.ensure_factor_metadata_sqlite_store",
        lambda: calls.append("factor_metadata") or str(sqlite_path),
    )

    class DummyHub:
        def ensure_visits_schema(self):
            calls.append("visits")

    monkeypatch.setattr("tools.data.hub.DataHub.get_instance", lambda: DummyHub())

    path = unified_sqlite.ensure_unified_sqlite_store()
    assert path == str(sqlite_path)
    assert calls == ["data_source", "users", "factor_metadata", "visits"]
