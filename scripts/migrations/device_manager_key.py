"""Review and migrate the device metadata key; never changes Keycloak grants.

Run a read-only inventory first. Apply requires that inventory digest and an
independently created, verified PostgreSQL backup. If independent Manager
bindings have subsequently been created, reverting to a device-only key
requires a separately reviewed mapping; it cannot be done by dropping rows.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


def inspect(connection) -> dict:
    """Return bounded, hashed record identities and constraint evidence."""
    from psycopg.rows import dict_row, tuple_row

    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute("""
        SELECT c.conname, array_agg(a.attname ORDER BY x.ordinality) AS columns
        FROM pg_constraint c
        CROSS JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS x(attnum, ordinality)
        JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=x.attnum
        WHERE c.conrelid='control_devices'::regclass AND c.contype='p'
        GROUP BY c.conname
        """).fetchone()
    if not row:
        raise ValueError('control_devices has no primary key')
    columns = list(row['columns'])
    if columns not in (['device_id'], ['source_server_id', 'device_id']):
        raise ValueError('unexpected device primary key')
    with connection.cursor(row_factory=tuple_row) as cursor:
        dependencies = cursor.execute("""
        SELECT count(*) FROM pg_constraint
        WHERE confrelid='control_devices'::regclass AND contype='f'
        """).fetchone()[0]
        counts = cursor.execute("""
        SELECT count(*), count(*) FILTER (WHERE source_server_id='' OR device_id=''),
          count(*) - count(DISTINCT (source_server_id, device_id))
        FROM control_devices
        """).fetchone()
    if counts[0] > 100_000:
        raise ValueError('device inventory exceeds review budget')
    digest = hashlib.sha256()
    with connection.cursor(name='device_migration_inventory', row_factory=tuple_row) as cursor:
        cursor.execute("""SELECT to_jsonb(d)::text FROM control_devices d
                          ORDER BY source_server_id, device_id""")
        while batch := cursor.fetchmany(501):
            for (value,) in batch:
                digest.update(value.encode('utf-8') + b'\n')
    evidence = {'count': counts[0], 'invalid_identity_count': counts[1],
                'duplicate_binding_count': counts[2], 'foreign_key_count': dependencies,
                'records_sha256': digest.hexdigest(), 'primary_key': columns,
                'constraint_name': row['conname']}
    evidence['plan_sha256'] = hashlib.sha256(json.dumps(
        evidence, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return evidence


def migrate(connection, *, apply: bool = False, reviewed_plan_sha256: str = '') -> dict:
    """Apply under a lock only if the entire reviewed snapshot is unchanged."""
    from psycopg import sql

    if apply:
        connection.execute('LOCK TABLE control_devices IN ACCESS EXCLUSIVE MODE')
    before = inspect(connection)
    if not apply:
        return {'mode': 'dry-run', **before}
    if before['plan_sha256'] != reviewed_plan_sha256:
        raise ValueError('device inventory changed or review digest is invalid')
    if before['invalid_identity_count'] or before['duplicate_binding_count'] or before['foreign_key_count']:
        raise ValueError('device inventory has invalid bindings or dependent foreign keys')
    if before['primary_key'] == ['device_id']:
        connection.execute(sql.SQL('ALTER TABLE control_devices DROP CONSTRAINT {}').format(
            sql.Identifier(before['constraint_name'])))
        connection.execute('ALTER TABLE control_devices ADD PRIMARY KEY (source_server_id, device_id)')
    after = inspect(connection)
    if (after['records_sha256'] != before['records_sha256'] or after['count'] != before['count']
            or after['primary_key'] != ['source_server_id', 'device_id']):
        raise ValueError('device migration did not preserve all records')
    return {'mode': 'apply', 'before': before, 'after': after}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dsn-env', required=True, help='environment variable containing the PostgreSQL DSN')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--reviewed-plan-sha256', default='')
    parser.add_argument('--backup', type=Path)
    args = parser.parse_args()
    dsn = os.environ.get(args.dsn_env, '')
    if not dsn:
        parser.error('database DSN environment variable is empty')
    backup_sha = None
    if args.apply:
        if not args.backup or not args.backup.is_file() or args.backup.stat().st_size == 0:
            parser.error('apply requires a nonempty PostgreSQL backup; verify restoration separately')
        with args.backup.open('rb') as source:
            backup_sha = hashlib.file_digest(source, 'sha256').hexdigest()
    import psycopg
    with psycopg.connect(dsn) as connection:
        result = migrate(connection, apply=args.apply, reviewed_plan_sha256=args.reviewed_plan_sha256)
        if not args.apply:
            connection.rollback()
    if backup_sha:
        result['backup_sha256'] = backup_sha
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
