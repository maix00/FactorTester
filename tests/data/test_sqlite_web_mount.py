from __future__ import annotations

import json

from server import create_app
from server.services import accounts as account_store
from server.services import sqlite_web_mount
from server.services import user_sqlite
from sources.OpenCTP import client as openctp_client
from sqlite_web.sqlite_web import datasets


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def test_users_sqlite_mirror_is_loaded_by_sqlite_web(monkeypatch, tmp_path):
    data_dir = tmp_path / 'data'
    users_dir = data_dir / 'users'
    openctp_db = tmp_path / 'cache' / 'openctp' / 'openctp.sqlite'
    users_db = tmp_path / 'cache' / 'sqlite-web' / 'users.sqlite'

    monkeypatch.setattr(account_store, 'ACCOUNTS_FILE', str(users_dir / 'accounts.json'))
    monkeypatch.setattr(account_store, 'ORGANIZATIONS_FILE', str(users_dir / 'organizations.json'))
    monkeypatch.setattr(account_store, 'LEVELS_FILE', str(users_dir / 'levels.json'))
    monkeypatch.setattr(openctp_client, 'CACHE_DIR', tmp_path / 'cache' / 'openctp')
    monkeypatch.setattr(openctp_client, 'CACHE_DB_PATH', openctp_client.CACHE_DIR / 'openctp.sqlite')
    monkeypatch.setattr(user_sqlite, 'USER_SQLITE_DIR', users_db.parent)
    monkeypatch.setattr(user_sqlite, 'USER_SQLITE_PATH', users_db)
    monkeypatch.setattr(sqlite_web_mount, '_mounted_app', None)

    _write_json(users_dir / 'accounts.json', [{
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
    _write_json(users_dir / 'organizations.json', [{
        'id': 'default',
        'name': '默认机构',
        'description': '系统默认机构',
    }])
    _write_json(users_dir / 'levels.json', [{
        'id': 'default__ROOT',
        'organization_id': 'default',
        'name': '默认层级',
        'parent_level_id': '',
        'manager_username': '',
    }])

    datasets.clear()
    app = create_app()

    assert openctp_db.exists()
    assert users_db.exists()
    assert set(datasets.keys()) == {'openctp.sqlite', 'users.sqlite'}

    client = app.test_client()
    resp = client.get('/sqlite-web/')
    assert resp.status_code == 302
    assert '/?next=/sqlite-web/' in resp.headers['Location']

    with client.session_transaction() as sess:
        sess['username'] = 'default$alice@1'
        sess['_sid'] = 'sid-1'
    resp = client.get('/sqlite-web/')
    assert resp.status_code == 200
