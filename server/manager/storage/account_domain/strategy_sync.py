"""Strategy metadata projections; executable bytes use the object data plane."""
from __future__ import annotations

import hashlib
import json

from server.services.strategy_library.store import StrategyLibraryStore
from tools.data.sqlite.db import connect_sqlite


def revision_bytes(revision: dict) -> bytes:
    return json.dumps(revision, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()


def backfill_strategies(sync, principal: str) -> int:
    with connect_sqlite(sync.local.path, readonly=True) as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='strategy_library_entries'").fetchone() is None:
            return 0
        rows = db.execute('SELECT strategy_ref FROM strategy_library_entries WHERE owner_ref=?', (principal,)).fetchall()
    count = 0
    for row in rows:
        if sync.local.get_entity(principal, 'strategy', row['strategy_ref']) is None:
            publish_strategy(sync, row['strategy_ref'], principal)
            count += 1
    return count


def publish_strategy(sync, strategy_ref: str, principal: str) -> None:
    store = StrategyLibraryStore(sync.local.path)
    entry = store.get_entry(strategy_ref)
    if entry is None:
        sync.delete(principal, 'strategy', strategy_ref, flush=False)
        return
    owner = entry['owner_ref']
    shares = store.shares(strategy_ref)
    visibility = 'authorized' if entry['visibility'] == 'shared' else entry['visibility']
    policy = {'visibility': visibility, 'authorized_users': shares}
    for summary in store.list_revisions(strategy_ref):
        ref = summary['revision_ref']
        previous = sync.local.get_entity(owner, 'strategy_revision', ref)
        manifest = dict(previous['payload']) if previous else {}
        revision = store.get_revision(ref)
        if revision and revision.get('source_code'):
            raw = revision_bytes(revision)
            manifest = {**summary, 'owner_ref': owner,
                        'storage_server_id': manifest.get('storage_server_id') or sync.manager_id,
                        'object_bytes': len(raw), 'object_sha256': hashlib.sha256(raw).hexdigest()}
        if not manifest:
            raise ValueError('strategy revision source is unavailable')
        sync.upsert(owner, 'strategy_revision', ref, {**manifest, **policy}, flush=False)
    sync.upsert(owner, 'strategy', strategy_ref,
                {**entry, 'entry_visibility': entry['visibility'], **policy, 'shares': shares}, flush=False)


def materialize_strategy(database, row: dict) -> None:
    """Install metadata without overwriting locally hydrated immutable bytes."""
    kind = row['entity_type']
    if kind not in {'strategy', 'strategy_revision'}:
        return
    StrategyLibraryStore(database)
    value = row.get('payload') or {}
    identifier = row['entity_id']
    with connect_sqlite(database) as db:
        if row.get('deleted'):
            if kind == 'strategy':
                db.execute('UPDATE strategy_library_entries SET deleted_at=1 WHERE strategy_ref=?', (identifier,))
            return
        if kind == 'strategy_revision':
            db.execute('''INSERT INTO strategy_library_revisions
                (revision_ref,strategy_ref,revision_number,source_sha256,source_code,entrypoint,
                 hooks_json,requirements_json,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(revision_ref) DO NOTHING''',
                (identifier, value['strategy_ref'], value['revision_number'], value['source_sha256'], '',
                 value['entrypoint'], json.dumps(value.get('hooks') or []),
                 json.dumps(value.get('requirements') or {}), value['created_by'], value['created_at']))
            return
        db.execute('''INSERT INTO strategy_library_entries
            (strategy_ref,owner_ref,name,description,visibility,current_revision_ref,created_at,updated_at,deleted_at)
            VALUES (?,?,?,?,?,?,?,?,0) ON CONFLICT(strategy_ref) DO UPDATE SET
            name=excluded.name,description=excluded.description,visibility=excluded.visibility,
            current_revision_ref=excluded.current_revision_ref,updated_at=excluded.updated_at,deleted_at=0''',
            (identifier, value['owner_ref'], value['name'], value['description'], value['entry_visibility'],
             value['current_revision_ref'], value['created_at'], value['updated_at']))
        db.execute('DELETE FROM strategy_library_shares WHERE strategy_ref=?', (identifier,))
        db.executemany('INSERT INTO strategy_library_shares VALUES (?,?,?)',
                       [(identifier, target, value['updated_at']) for target in value.get('shares') or []])
