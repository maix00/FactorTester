"""Real PostgreSQL migration test; DSN must point to an isolated test database."""
from contextlib import contextmanager
import os
from uuid import uuid4

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get('TR_TEST_DEVICE_POSTGRES_DSN'),
                                reason='isolated PostgreSQL test DSN not configured')


def test_migration_preserves_records_and_isolates_manager_bindings():
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row
    from scripts.migrations.device_manager_key import migrate
    from server.manager.storage.control_db import CONTROL_SCHEMA, PostgresControlStore

    dsn = os.environ['TR_TEST_DEVICE_POSTGRES_DSN']
    schema = 'device_test_' + uuid4().hex

    @contextmanager
    def scoped_connection():
        with psycopg.connect(dsn, row_factory=dict_row) as connection:
            connection.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
            yield connection

    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    try:
        with scoped_connection() as connection:
            ddl = CONTROL_SCHEMA[1].replace('PRIMARY KEY (source_server_id, device_id)',
                                            'PRIMARY KEY (device_id)')
            connection.execute(ddl)
            connection.execute("""INSERT INTO control_devices(device_id,public_key,username,source_server_id)
                               VALUES ('device-shared-123456', '{}', 'alice', 'public')""")
        with scoped_connection() as connection:
            dry = migrate(connection)
        assert dry['count'] == 1 and dry['primary_key'] == ['device_id']
        assert len(dry['mappings']) == 1 and dry['mappings'][0]['action'] == 'preserve'
        assert 'device-shared-123456' not in str(dry)
        with scoped_connection() as connection:
            connection.execute('CREATE TABLE dependent_device (device_id TEXT REFERENCES control_devices(device_id))')
        with scoped_connection() as connection:
            dependency_plan = migrate(connection)
        assert dependency_plan['foreign_key_count'] == 1
        with pytest.raises(ValueError, match='dependent foreign keys'):
            with scoped_connection() as connection:
                migrate(connection, apply=True, reviewed_plan_sha256=dependency_plan['plan_sha256'])
        with scoped_connection() as connection:
            connection.execute('DROP TABLE dependent_device')
        with pytest.raises(ValueError, match='inventory changed'):
            with scoped_connection() as connection:
                migrate(connection, apply=True, reviewed_plan_sha256='wrong')
        with scoped_connection() as connection:
            result = migrate(connection, apply=True, reviewed_plan_sha256=dry['plan_sha256'])
        assert result['after']['records_sha256'] == dry['records_sha256']
        assert result['after']['mappings'] == dry['mappings']
        store = object.__new__(PostgresControlStore)
        store.ensure_schema = lambda: None
        store._connection = scoped_connection
        store.enroll_device(device_id='device-shared-123456', public_key={},
                            username='alice', source_server_id='lan')
        assert store.device('device-shared-123456', source_server_id='lan')['enabled']
        assert store.device('device-shared-123456', source_server_id='public')['enabled']
        store.revoke_device('device-shared-123456', source_server_id='lan', username='alice', public_key={})
        assert not store.device('device-shared-123456', source_server_id='lan')['enabled']
        assert store.device('device-shared-123456', source_server_id='public')['enabled']
        assert len(store.list_devices(username='alice', source_server_id='lan')) == 1
        assert store.public_device_total_count(username='alice', source_server_id='lan') == 0
        assert store.public_device_total_count(username='alice', source_server_id='public') == 1
        assert store.public_device_user_count(source_server_id='lan') == 0
        assert store.public_device_user_count(source_server_id='public') == 1
    finally:
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
