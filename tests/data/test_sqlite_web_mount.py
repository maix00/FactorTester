from __future__ import annotations

import settings as Settings
from server import create_app
from tools.data.sqlite import account_manager as account_store
from tools.data.sqlite import data_source as data_source_sqlite
from sources.OpenCTP import client as openctp_client


def test_users_sqlite_mirror_is_loaded_by_sqlite_web(monkeypatch, tmp_path):
    unified_db = tmp_path / 'cache' / 'localdata' / 'unifieddata.sqlite'

    monkeypatch.setattr(Settings, 'CACHE_DIR', tmp_path / 'cache' / 'localdata')
    monkeypatch.setattr(Settings, 'CACHE_DB_PATH', unified_db)
    monkeypatch.setattr(openctp_client, 'CACHE_DIR', Settings.CACHE_DIR)
    monkeypatch.setattr(openctp_client, 'CACHE_DB_PATH', Settings.CACHE_DB_PATH)
    monkeypatch.setattr(data_source_sqlite, 'PREVIEW_PRODUCTS_PER_SOURCE', 0)

    account_store.save_accounts([{
        'username': 'default$alice@1',
        'alias': 'alice',
        'salt': 'salt',
        'hash': 'hash',
        'role': 'user',
        'is_admin': False,
        'organization_id': 'default',
        'organization_name': '默认机构',
        'level_id': 'default__ROOT',
        'parent_username': '',
    }])
    account_store.save_organizations([{
        'id': 'default',
        'name': '默认机构',
        'description': '系统默认机构',
    }])
    account_store.save_levels([{
        'id': 'default__ROOT',
        'organization_id': 'default',
        'name': '默认层级',
        'parent_level_id': '',
        'manager_username': '',
    }])

    app = create_app()

    assert unified_db.exists()
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
