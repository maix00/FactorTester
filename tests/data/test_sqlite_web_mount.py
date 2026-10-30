from __future__ import annotations

import settings as Settings
from server import create_app
from tools.data.sqlite import account_manager as account_store
from tools.data.sqlite import data_source as data_source_sqlite
from sources.OpenCTP import client as openctp_client


def test_keycloak_directory_is_not_materialized_in_local_sqlite(monkeypatch, tmp_path):
    unified_db = tmp_path / 'cache' / 'localdata' / 'unifieddata.sqlite'

    monkeypatch.setattr(Settings, 'CACHE_DIR', tmp_path / 'cache' / 'localdata')
    monkeypatch.setattr(Settings, 'CACHE_DB_PATH', unified_db)
    monkeypatch.setattr(openctp_client, 'CACHE_DIR', Settings.CACHE_DIR)
    monkeypatch.setattr(openctp_client, 'CACHE_DB_PATH', Settings.CACHE_DB_PATH)
    monkeypatch.setattr(data_source_sqlite, 'PREVIEW_PRODUCTS_PER_SOURCE', 0)

    account_store.ensure_account_manager_sqlite_store()

    app = create_app()

    assert unified_db.exists()
    import sqlite3
    with sqlite3.connect(unified_db) as connection:
        local_identity_tables = {
            str(row[0]) for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        } & {"accounts", "organizations", "levels"}
    assert local_identity_tables == set()
    # The business service no longer owns any browser or database page.
    # Manager 7998 mounts sqlite-web itself; service-port web paths are absent.
    client = app.test_client()
    for path in (
        '/',
        '/products',
        '/jobs',
        '/sqlite-web/',
        '/local-data',
        '/api/local-data/stores',
        '/api/local-data/openctp/tables',
        '/api/local-data/openctp/table/accounts',
    ):
        response = client.get(path)
        assert response.status_code == 404
