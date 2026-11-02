from contextlib import contextmanager
import json

from server.manager.storage.control_db import PostgresControlStore


def test_postgres_revoke_matches_source_owner_and_key_atomically():
    key = {'kty': 'EC', 'crv': 'P-256', 'x': 'A' * 43, 'y': 'A' * 43}
    state = {'enabled': True, 'device_id': 'device-123456789', 'source_server_id': 'remote',
             'username': 'alice', 'public_key': key}

    class Connection:
        def execute(self, sql, args):
            assert 'device_id=%s AND source_server_id=%s' in sql
            assert 'username=%s AND public_key=%s::jsonb' in sql
            identifier, source, owner, encoded_key = args
            self.result = None
            if (identifier, source, owner, json.loads(encoded_key)) == (
                state['device_id'], state['source_server_id'], state['username'], state['public_key']
            ):
                state['enabled'] = False
                self.result = dict(state)
            return self

        def fetchone(self):
            return self.result

    @contextmanager
    def connection():
        yield Connection()

    store = object.__new__(PostgresControlStore)
    store.ensure_schema = lambda: None
    store._connection = connection
    assert store.revoke_device(state['device_id'], source_server_id='local', username='alice', public_key=key) is None
    assert state['enabled'] is True
    assert store.revoke_device(state['device_id'], source_server_id='remote', username='bob', public_key=key) is None
    assert state['enabled'] is True
    changed_key = {**key, 'x': 'B' * 43}
    assert store.revoke_device(state['device_id'], source_server_id='remote', username='alice', public_key=changed_key) is None
    assert state['enabled'] is True
    assert store.revoke_device(state['device_id'], source_server_id='remote', username='alice', public_key=key)['enabled'] is False


def test_postgres_device_touch_is_bound_to_origin():
    calls = []

    class Connection:
        def execute(self, sql, args):
            calls.append((sql, args))

    @contextmanager
    def connection():
        yield Connection()

    store = object.__new__(PostgresControlStore)
    store.ensure_schema = lambda: None
    store._connection = connection
    store.touch_device('device-123456789', source_server_id='local', last_seen_ip='192.0.2.1')
    assert 'WHERE device_id=%s AND source_server_id=%s AND enabled=TRUE' in calls[0][0]
    assert calls[0][1][-2:] == ('device-123456789', 'local')
