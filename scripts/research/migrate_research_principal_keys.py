"""Explicit, lossless membership/workspace key migration. Dry-run by default.

Stop Manager writers before applying; deployment must not invoke this implicitly.
Only relationship keys change. No report bytes, tombstones, or outbox are authored.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3

TABLES = ('research_catalog_memberships', 'research_catalog_workspaces')


def inventory(conn):
    result = {}
    for table in TABLES:
        schema = conn.execute('SELECT sql FROM sqlite_master WHERE name=?', (table,)).fetchone()
        if schema is None:
            raise ValueError(f'missing relationship table: {table}')
        rows = [dict(row) for row in conn.execute(f'SELECT * FROM {table} ORDER BY research_id,principal_ref,profile_ref')]
        invalid = [row for row in rows if not all(str(row[key]).strip() for key in ('research_id', 'principal_ref', 'profile_ref'))]
        result[table] = {
            'count': len(rows),
            'hash': hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest(),
            'invalid_identity_count': len(invalid),
            'mapping': [{'old': [r['research_id'], r['profile_ref']],
                         'new': [r['research_id'], r['principal_ref'], r['profile_ref']],
                         'workspace_id': r.get('workspace_id'), 'status': r['status']} for r in rows],
            'requires_migration': bool(re.search(r'(?:PRIMARY KEY|UNIQUE)\s*\(research_id,\s*profile_ref\)', schema[0])),
        }
    return result


def migrate(database: Path, *, backup: Path | None = None):
    with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as source:
        source.row_factory = sqlite3.Row
        plan = inventory(source)
        if backup is None:
            return {'dry_run': True, 'tables': plan}
        if any(item['invalid_identity_count'] for item in plan.values()):
            raise ValueError('invalid identities require review; migration refused')
        if backup.exists() or backup.resolve() == database.resolve():
            raise ValueError('backup must be a new, distinct path')
        backup.parent.mkdir(parents=True, exist_ok=True)
        # The full SQLite backup may contain sessions. Create it exclusively
        # with owner-only permissions before SQLite opens the destination.
        descriptor = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        with sqlite3.connect(backup) as target:
            source.backup(target)
            if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('backup integrity check failed')
    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('BEGIN IMMEDIATE')
        if inventory(conn) != plan:
            raise ValueError('relationships changed after backup; retry with writers stopped')
        for table, item in plan.items():
            if not item['requires_migration']:
                continue
            sql = conn.execute('SELECT sql FROM sqlite_master WHERE name=?', (table,)).fetchone()[0]
            indexes = [row[0] for row in conn.execute(
                "SELECT sql FROM sqlite_master WHERE tbl_name=? AND type='index' AND sql IS NOT NULL", (table,))]
            replacement = re.sub(r'((?:PRIMARY KEY|UNIQUE)\s*\()research_id,\s*profile_ref\)',
                                 r'\1research_id, principal_ref, profile_ref)', sql)
            replacement = replacement.replace(table, table + '_principal_migration', 1)
            conn.execute(replacement)
            conn.execute(f'INSERT INTO {table}_principal_migration SELECT * FROM {table}')
            conn.execute(f'DROP TABLE {table}')
            conn.execute(f'ALTER TABLE {table}_principal_migration RENAME TO {table}')
            for index in indexes:
                conn.execute(index)
        after = inventory(conn)
        if any(after[t]['hash'] != plan[t]['hash'] or after[t]['count'] != plan[t]['count'] for t in TABLES):
            raise ValueError('relationship preservation check failed')
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('database integrity check failed')
    return {'dry_run': False, 'backup': str(backup), 'tables': after}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    parser.add_argument('--apply-backup', type=Path, help='Apply after creating this new backup; omit for dry-run')
    args = parser.parse_args()
    print(json.dumps(migrate(args.database, backup=args.apply_backup), ensure_ascii=False, indent=2))
