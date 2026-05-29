"""
Tests for GroupTest settings snapshot persistence endpoints.
"""
from __future__ import annotations

import os
import tempfile

import pytest
from flask import Flask

import server.services.user_storage as user_storage


@pytest.fixture
def app_and_data():
    """Create a fresh Flask test app and temp data dir for each test."""
    original_data_dir = user_storage.DATA_DIR
    original_users_dir = user_storage.USERS_DIR
    from server.modules.single_factor_test import sft_bp
    with tempfile.TemporaryDirectory() as tmp:
        user_storage.DATA_DIR = os.path.join(tmp, 'data')
        user_storage.USERS_DIR = os.path.join(user_storage.DATA_DIR, 'users')
        # Also patch the canonical module so settings.py sees the change
        import server.services.user_storage as _canonical
        _canonical.DATA_DIR = user_storage.DATA_DIR
        _canonical.USERS_DIR = user_storage.USERS_DIR

        app = Flask(__name__)
        app.secret_key = 'test-secret'
        app.register_blueprint(sft_bp)
        yield app
        _canonical.DATA_DIR = original_data_dir
        _canonical.USERS_DIR = original_users_dir
        user_storage.DATA_DIR = original_data_dir
        user_storage.USERS_DIR = original_users_dir


def _auth_client(app):
    """Create a test client with an authenticated session."""
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['username'] = 'test_user'
        sess['_sid'] = 'test-sid-123'
    return client


class TestSaveGroupSettings:
    def test_save_success(self, app_and_data):
        client = _auth_client(app_and_data)
        payload = {
            'factor_alias': 'MmRet',
            'name': 'My Snapshot',
            'config': {
                'baseGroups': [{'id': 'bg1', 'name': 'G1'}],
                'derivedGraph': [],
                'lsConfigs': [],
                'registrations': [],
            },
        }
        resp = client.post('/save_group_settings', json=payload)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['saved']['name'] == 'My Snapshot'
        assert 'id' in data['saved']
        assert 'config' in data['saved']
        assert data['saved']['config']['baseGroups'][0]['id'] == 'bg1'

    def test_save_no_name_defaults(self, app_and_data):
        client = _auth_client(app_and_data)
        payload = {
            'factor_alias': 'MmRet',
            'config': {'baseGroups': [], 'derivedGraph': [], 'lsConfigs': [], 'registrations': []},
        }
        resp = client.post('/save_group_settings', json=payload)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['saved']['name'] == '未命名快照'

    def test_save_missing_factor_alias(self, app_and_data):
        client = _auth_client(app_and_data)
        resp = client.post('/save_group_settings', json={'config': {}})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data['success'] is False
        assert 'factor_alias' in data['error']

    def test_save_empty_body(self, app_and_data):
        client = _auth_client(app_and_data)
        resp = client.post('/save_group_settings', json={})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data['success'] is False

    def test_save_multiple_shows_up_in_list(self, app_and_data):
        client = _auth_client(app_and_data)
        for i in range(3):
            client.post('/save_group_settings', json={
                'factor_alias': 'MmCCI',
                'name': f'Snap {i}',
                'config': {'baseGroups': [{'id': f'bg{i}'}], 'derivedGraph': [], 'lsConfigs': [], 'registrations': []},
            })
        resp = client.post('/list_group_settings', json={'factor_alias': 'MmCCI'})
        data = resp.get_json()
        assert data['success'] is True
        assert len(data['snapshots']) == 3
        names = [s['name'] for s in data['snapshots']]
        assert names == ['Snap 0', 'Snap 1', 'Snap 2']

    def test_different_factors_isolated(self, app_and_data):
        client = _auth_client(app_and_data)
        # Save one for MmRet, one for MmCCI
        client.post('/save_group_settings', json={
            'factor_alias': 'MmRet', 'name': 'RetSnap',
            'config': {'baseGroups': [], 'derivedGraph': [], 'lsConfigs': [], 'registrations': []},
        })
        client.post('/save_group_settings', json={
            'factor_alias': 'MmCCI', 'name': 'CCISnap',
            'config': {'baseGroups': [], 'derivedGraph': [], 'lsConfigs': [], 'registrations': []},
        })
        # List MmRet
        resp = client.post('/list_group_settings', json={'factor_alias': 'MmRet'})
        data = resp.get_json()
        assert len(data['snapshots']) == 1
        assert data['snapshots'][0]['name'] == 'RetSnap'

        # List MmCCI
        resp = client.post('/list_group_settings', json={'factor_alias': 'MmCCI'})
        data = resp.get_json()
        assert len(data['snapshots']) == 1
        assert data['snapshots'][0]['name'] == 'CCISnap'

    def test_requires_auth(self, app_and_data):
        """Without session, require_user should fail."""
        resp = app_and_data.test_client().post('/save_group_settings', json={
            'factor_alias': 'MmRet', 'config': {},
        })
        data = resp.get_json()
        # When assert fails in require_user, Flask returns 500
        assert not data.get('success', True)


class TestLoadGroupSettings:
    def test_load_existing(self, app_and_data):
        client = _auth_client(app_and_data)
        # Save first
        save_resp = client.post('/save_group_settings', json={
            'factor_alias': 'MmRet',
            'name': 'Test Load',
            'config': {
                'baseGroups': [{'id': 'x', 'name': 'X'}],
                'derivedGraph': [{'id': 'd1', 'nodeType': 'derived'}],
                'lsConfigs': [{'id': 'ls1', 'name': 'LS1'}],
                'registrations': [],
            },
        })
        saved_id = save_resp.get_json()['saved']['id']

        # Load it
        resp = client.post('/load_group_settings', json={
            'factor_alias': 'MmRet', 'id': saved_id,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['snapshot']['name'] == 'Test Load'
        assert len(data['snapshot']['config']['baseGroups']) == 1
        assert len(data['snapshot']['config']['derivedGraph']) == 1
        assert len(data['snapshot']['config']['lsConfigs']) == 1

    def test_load_nonexistent(self, app_and_data):
        client = _auth_client(app_and_data)
        resp = client.post('/load_group_settings', json={
            'factor_alias': 'MmRet', 'id': 'nonexistent-id',
        })
        assert resp.status_code == 404
        data = resp.get_json()
        assert data['success'] is False

    def test_load_missing_id(self, app_and_data):
        client = _auth_client(app_and_data)
        resp = client.post('/load_group_settings', json={'factor_alias': 'MmRet'})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data['success'] is False


class TestListGroupSettings:
    def test_list_empty(self, app_and_data):
        client = _auth_client(app_and_data)
        resp = client.post('/list_group_settings', json={'factor_alias': 'NoFactor'})
        data = resp.get_json()
        assert data['success'] is True
        assert data['snapshots'] == []

    def test_list_with_summaries(self, app_and_data):
        client = _auth_client(app_and_data)
        client.post('/save_group_settings', json={
            'factor_alias': 'MmRet', 'name': 'S1',
            'config': {
                'baseGroups': [{'id': 'a'}, {'id': 'b'}, {'id': 'c'}],
                'derivedGraph': [{'id': 'd1'}],
                'lsConfigs': [{'id': 'l1'}, {'id': 'l2'}],
                'registrations': [{'lsConfigId': 'l1', 'registrations': []}],
            },
        })
        resp = client.post('/list_group_settings', json={'factor_alias': 'MmRet'})
        data = resp.get_json()
        assert data['success'] is True
        assert len(data['snapshots']) == 1
        s = data['snapshots'][0]
        assert s['config_summary']['baseGroups'] == 3
        assert s['config_summary']['derivedGraph'] == 1
        assert s['config_summary']['lsConfigs'] == 2
        assert s['config_summary']['registrations'] == 1

    def test_list_missing_factor_alias(self, app_and_data):
        client = _auth_client(app_and_data)
        resp = client.post('/list_group_settings', json={})
        assert resp.status_code == 400


class TestDeleteGroupSettings:
    def test_delete_existing(self, app_and_data):
        client = _auth_client(app_and_data)
        # Save
        save_resp = client.post('/save_group_settings', json={
            'factor_alias': 'MmRet', 'name': 'ToDelete',
            'config': {'baseGroups': [], 'derivedGraph': [], 'lsConfigs': [], 'registrations': []},
        })
        saved_id = save_resp.get_json()['saved']['id']

        # Delete
        resp = client.post('/delete_group_settings', json={
            'factor_alias': 'MmRet', 'id': saved_id,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['deleted_id'] == saved_id

        # Verify gone
        list_resp = client.post('/list_group_settings', json={'factor_alias': 'MmRet'})
        assert len(list_resp.get_json()['snapshots']) == 0

    def test_delete_nonexistent(self, app_and_data):
        client = _auth_client(app_and_data)
        resp = client.post('/delete_group_settings', json={
            'factor_alias': 'MmRet', 'id': 'no-such-id',
        })
        assert resp.status_code == 404
        data = resp.get_json()
        assert data['success'] is False

    def test_delete_missing_id(self, app_and_data):
        client = _auth_client(app_and_data)
        resp = client.post('/delete_group_settings', json={'factor_alias': 'MmRet'})
        assert resp.status_code == 400

    def test_delete_only_correct_one(self, app_and_data):
        client = _auth_client(app_and_data)
        # Save two
        r1 = client.post('/save_group_settings', json={
            'factor_alias': 'MmRet', 'name': 'Keep',
            'config': {'baseGroups': [], 'derivedGraph': [], 'lsConfigs': [], 'registrations': []},
        })
        r2 = client.post('/save_group_settings', json={
            'factor_alias': 'MmRet', 'name': 'Delete',
            'config': {'baseGroups': [], 'derivedGraph': [], 'lsConfigs': [], 'registrations': []},
        })
        id1 = r1.get_json()['saved']['id']
        id2 = r2.get_json()['saved']['id']

        # Verify both exist before delete
        list_before = client.post('/list_group_settings', json={'factor_alias': 'MmRet'})
        assert len(list_before.get_json()['snapshots']) == 2

        # Delete the second one
        client.post('/delete_group_settings', json={'factor_alias': 'MmRet', 'id': id2})

        # Verify only first remains
        list_resp = client.post('/list_group_settings', json={'factor_alias': 'MmRet'})
        snapshots = list_resp.get_json()['snapshots']
        assert len(snapshots) == 1
        assert snapshots[0]['id'] == id1
        assert snapshots[0]['name'] == 'Keep'


class TestSanitizedFactorAlias:
    def test_special_characters_in_alias(self, app_and_data):
        """Factor aliases with slashes should be sanitized for filesystem."""
        client = _auth_client(app_and_data)
        payload = {
            'factor_alias': 'Group/Factor\\Test',
            'name': 'Special',
            'config': {'baseGroups': [], 'derivedGraph': [], 'lsConfigs': [], 'registrations': []},
        }
        resp = client.post('/save_group_settings', json=payload)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True

        # Should be loadable with same alias
        saved_id = data['saved']['id']
        load_resp = client.post('/load_group_settings', json={
            'factor_alias': 'Group/Factor\\Test', 'id': saved_id,
        })
        assert load_resp.get_json()['success'] is True
