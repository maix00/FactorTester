"""Create a protected, read-only legacy-device to Keycloak identity inventory.

The input is a reviewed device export and a reviewed Keycloak directory. This
does not inspect live Keycloak grants, create grants, or perform a cutover.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path

from server.identity.device_migration_inventory import classify_devices


def read_postgres_snapshot(connection, *, manager_id: str, principal: str) -> dict:
    """Read a single principal in one read-only snapshot without schema setup."""
    if not isinstance(principal, str) or not principal.strip() or len(principal) > 256:
        raise ValueError('a scoped principal is required')
    connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    columns = connection.execute('''SELECT column_name FROM information_schema.columns
        WHERE table_schema=current_schema() AND table_name='control_devices'
          AND column_name IN ('public_access','quota_exempt')''').fetchall()
    names = {str(row['column_name']) for row in columns}
    optional = [name for name in ('public_access', 'quota_exempt') if name in names]
    fields = ['device_id', 'username', 'public_key', 'enabled', 'source_server_id', *optional]
    records: list[dict] = []
    after = ''
    while True:
        # The interpolated identifiers are chosen only from the fixed list above.
        rows = connection.execute(f'''SELECT {', '.join(fields)} FROM control_devices
            WHERE username=%s AND device_id>%s ORDER BY device_id LIMIT %s''',
            (principal, after, 501)).fetchall()
        if len(records) + len(rows) > 100_000:
            raise ValueError('device snapshot records exceed the inventory budget')
        records.extend(dict(row) for row in rows)
        if len(rows) < 501:
            break
        after = str(rows[-1]['device_id'])
    return {'server_id': manager_id, 'devices': records, 'sources': {},
            'legacy_columns_present': optional}


def plan(snapshot: dict, directory: dict, *, manager_id: str) -> dict:
    if not isinstance(snapshot, dict) or not isinstance(directory, dict):
        raise ValueError('device snapshot and Keycloak directory must be objects')
    manager_id = str(manager_id or '').strip()
    if not manager_id or snapshot.get('server_id') != manager_id:
        raise ValueError('device snapshot belongs to another Manager')
    accounts = directory.get('accounts')
    if not isinstance(accounts, list) or len(accounts) > 100_000:
        raise ValueError('reviewed Keycloak directory is invalid or too large')
    identities: dict[str, list[dict]] = {}
    names: set[str] = set()
    stable_ids: set[str] = set()
    subjects: set[str] = set()
    for account in accounts:
        if not isinstance(account, dict) or not isinstance(account.get('username'), str) or not account['username'].strip():
            raise ValueError('reviewed Keycloak account is invalid')
        name = account['username'].casefold()
        stable, subject = account.get('tr_identity_id'), account.get('keycloak_subject')
        if (name in names or (isinstance(stable, str) and stable and stable in stable_ids)
                or (isinstance(subject, str) and subject and subject in subjects)):
            raise ValueError('reviewed Keycloak directory has duplicate identities')
        names.add(name)
        if isinstance(stable, str) and stable: stable_ids.add(stable)
        if isinstance(subject, str) and subject: subjects.add(subject)
        identities.setdefault(account['username'], []).append({
            'tr_identity_id': account.get('tr_identity_id'),
            'keycloak_subject': account.get('keycloak_subject'),
            'active': account.get('active'),
        })
    records = []
    devices = snapshot.get('devices')
    if isinstance(devices, dict):
        for device_id, value in devices.items():
            records.append({**value, 'device_id': device_id,
                            'source_server_id': value.get('source_server_id') or manager_id}
                           if isinstance(value, dict) else {'device_id': device_id})
    elif isinstance(devices, list):
        records.extend(devices)
    else:
        raise ValueError('device snapshot records are invalid')
    sources = snapshot.get('sources', {})
    if not isinstance(sources, dict):
        raise ValueError('device snapshot sources are invalid')
    for source_id, source in sources.items():
        if not isinstance(source, dict) or not isinstance(source.get('devices'), list):
            raise ValueError('device snapshot source is invalid')
        for value in source['devices']:
            records.append({**value, 'source_server_id': source_id} if isinstance(value, dict) else {})
    if len(records) > 100_000 or any(not isinstance(row, dict) for row in records):
        raise ValueError('device snapshot records are invalid or too large')
    entries = classify_devices(manager_id=manager_id, records=records, identities=identities)
    entries.sort(key=lambda item: (str(item.get('username') or ''), str(item.get('device_id') or '')))
    frozen = {'manager_id': manager_id, 'entries': entries}
    digest = hashlib.sha256(json.dumps(frozen, ensure_ascii=False, sort_keys=True,
                                      separators=(',', ':')).encode()).hexdigest()
    return {**frozen, 'summary': {'records': len(entries),
        'statuses': dict(sorted(Counter(item['status'] for item in entries).items())),
        'sha256': digest, 'keycloak_live_grants_checked': False,
        **({'legacy_columns_present': snapshot['legacy_columns_present']}
           if 'legacy_columns_present' in snapshot else {})}}


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--snapshot')
    source.add_argument('--postgres', action='store_true', help='read the configured control database without initializing it')
    parser.add_argument('--principal', help='required single principal when reading PostgreSQL')
    parser.add_argument('--reviewed-directory', required=True)
    parser.add_argument('--manager-id', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    if args.postgres:
        if not args.principal:
            parser.error('--postgres requires --principal')
        from server.manager.storage.control_db import ControlDatabaseConfig, PostgresControlStore
        config = ControlDatabaseConfig.from_env()
        if config is None:
            parser.error('the control database is not configured')
        connection = PostgresControlStore(config)._connect()
        try:
            snapshot = read_postgres_snapshot(connection, manager_id=args.manager_id, principal=args.principal)
        finally:
            connection.close()
    else:
        snapshot = json.loads(Path(args.snapshot).read_text())
    result = plan(snapshot, json.loads(Path(args.reviewed_directory).read_text()), manager_id=args.manager_id)
    fd = os.open(Path(args.output).expanduser(), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as output:
        json.dump(result, output, ensure_ascii=False, sort_keys=True)
    print(json.dumps(result['summary'], ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
