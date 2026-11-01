"""Check malformed legacy-device pagination in disposable PostgreSQL."""
from __future__ import annotations

import json

import psycopg
from psycopg.rows import dict_row

from scripts.migrations.keycloak_device_inventory import plan, read_postgres_snapshot
from scripts.test.postgres_sandbox import postgres_sandbox


def main() -> None:
    key = {'kty': 'EC', 'crv': 'P-256', 'x': 'A' * 43, 'y': 'A' * 43}
    with postgres_sandbox('tr-device-inventory') as settings:
        with psycopg.connect(**settings) as db:
            # Some older installations may not have current NOT NULL/PK
            # constraints. Inventory must still see every malformed record.
            db.execute('''CREATE TABLE control_devices (device_id text, username text,
                public_key jsonb, enabled boolean, source_server_id text)''')
            rows = [(f'device-{index:012d}', 'alice', json.dumps(key), True, 'lan') for index in range(501)]
            rows += [('', 'alice', json.dumps(key), True, ''),
                     (None, 'alice', json.dumps(key), True, None),
                     ('device-duplicate', 'alice', json.dumps(key), True, None),
                     ('device-duplicate', 'alice', json.dumps(key), True, None),
                     ('device-shared-12345', 'alice', json.dumps(key), True, 'lan'),
                     ('device-shared-12345', 'alice', json.dumps(key), True, 'public'),
                     ('other-owner', 'bob', json.dumps(key), True, 'lan')]
            with db.cursor() as cursor:
                cursor.executemany('INSERT INTO control_devices VALUES (%s,%s,%s::jsonb,%s,%s)', rows)
            db.commit()
        with psycopg.connect(**settings, row_factory=dict_row) as reader:
            snapshot = read_postgres_snapshot(reader, manager_id='lan', principal='alice')
        assert len(snapshot['devices']) == 507
        inventory = plan(snapshot, {'accounts': [{'username': 'alice', 'tr_identity_id': 'stable',
            'keycloak_subject': 'subject', 'active': True}]}, manager_id='lan')
        assert inventory['summary']['statuses']['needs_repair'] == 4, inventory['summary']['statuses']
        assert inventory['summary']['statuses']['outside_manager'] == 1
        assert len(inventory['entries']) == 507
        print(json.dumps({'real_postgres': True, 'records': len(inventory['entries']),
            'needs_repair': 4, 'outside_manager': 1, 'cutover_ready': False}, sort_keys=True))


if __name__ == '__main__':
    main()
