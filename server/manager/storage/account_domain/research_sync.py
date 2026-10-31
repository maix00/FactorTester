"""Bounded Research relationship projections for trusted Manager replicas.

The replication envelope is cluster-visible so revocations reach replicas that
previously cached a grant. It is not a public Research grant: all user-facing
reads must use ResearchCatalog's nested visibility/membership access policy.
No HTTP endpoint exposes this envelope or the account-domain store directly.
Report bytes and share-link capabilities are deliberately absent.
"""
from __future__ import annotations

import json
import hashlib
import time
from contextlib import nullcontext
from pathlib import Path

from tools.data.sqlite.db import connect_sqlite
from .payloads import public_payload

KIND = 'research_catalog'
TABLES = {
    'research': ('research_catalog_researches', ('research_id',)),
    'members': ('research_catalog_memberships', ('research_id', 'principal_ref', 'profile_ref')),
    'workspaces': ('research_catalog_workspaces', ('workspace_id',)),
    'reports': ('research_catalog_reports', ('report_id',)),
    'branches': ('research_catalog_branches', ('report_id', 'branch_id')),
    'evidence_links': ('research_catalog_report_evidence_links', ('link_ref',)),
}


def research_sync_lock(database, research_id: str):
    """Serialize same-Research writes and sends without a global DB lock."""
    from tools.cli.release.research_reporting.generation import report_workspace_lock
    ref = str(research_id or '').strip()
    if not ref or len(ref) > 512:
        raise ValueError('Research synchronization identity is invalid')
    shard = hashlib.sha256(ref.encode('utf-8')).hexdigest()[:2]
    return report_workspace_lock(Path(database).resolve().parent / '.research-sync-locks' / shard)


def snapshot(conn, research_id: str, *, research_row=None) -> dict | None:
    row = research_row if research_row is not None else conn.execute(
        'SELECT * FROM research_catalog_researches WHERE research_id=?', (research_id,)).fetchone()
    if row is None:
        return None
    value = {'research': dict(row)}
    for key, (table, primary) in TABLES.items():
        if key == 'research':
            continue
        where = ('report_id IN (SELECT report_id FROM research_catalog_reports WHERE research_id=?)'
                 if key == 'evidence_links' else 'research_id=?')
        value[key] = [dict(item) for item in conn.execute(
            f'SELECT * FROM {table} WHERE {where} ORDER BY {", ".join(primary)}', (research_id,),
        ).fetchall()]
    return value


def _legacy_visible(row: dict, owner: str) -> bool:
    visibility = str(row.get('visibility') or 'private')
    if visibility not in {'private', 'authorized', 'superiors', 'public'}:
        raise ValueError('invalid legacy Research visibility')
    users = json.loads(str(row.get('authorized_users_json') or '[]'))
    if not isinstance(users, list) or any(not isinstance(user, str) for user in users):
        raise ValueError('invalid legacy Research sharing metadata')
    return visibility in {'public', 'superiors'} or any(user.strip() and user.strip() != owner for user in users)


def _legacy_shared(value: dict) -> bool:
    """Identify a whole-Research share in a snapshot, never grant access.

    A report-only share must not authorize the enclosing Research graph.
    """
    research = value.get('research') or {}
    owner = str(research.get('owner_ref') or '')
    if not owner:
        raise ValueError('Research synchronization owner is missing')
    status = str(research.get('status') or '')
    if status not in {'active', 'archived'}:
        raise ValueError('invalid Research synchronization status')
    if status == 'archived':
        return False
    if value.get('sharing_scope') == 'research' or _legacy_visible(research, owner):
        return True
    if any(str(item.get('principal_ref') or '') != owner and item.get('status') in {'active', 'invited'}
           for item in value.get('members', [])):
        return True
    return False


def _legacy_current_shared(conn, research_id: str, research: dict) -> bool:
    """Check minimal metadata before materializing a whole Research graph."""
    owner = str(research.get('owner_ref') or '')
    status = str(research.get('status') or '')
    if not owner or status not in {'active', 'archived'}:
        raise ValueError('invalid Research synchronization identity or status')
    if status == 'archived':
        return False
    if _legacy_visible(research, owner):
        return True
    if conn.execute('''SELECT 1 FROM research_catalog_memberships WHERE research_id=? AND principal_ref<>?
        AND status IN ('active', 'invited') LIMIT 1''', (research_id, owner)).fetchone() is not None:
        return True
    return _legacy_has_live_share_link(conn, research_id)


def _legacy_has_live_share_link(conn, research_id: str) -> bool:
    return conn.execute('''SELECT 1 FROM research_catalog_share_links WHERE research_id=?
        AND target_kind='research' AND mode IN ('one_time', 'permanent') AND revoked_at=0
        AND (expires_at=0 OR expires_at>?) LIMIT 1''', (research_id, time.time())).fetchone() is not None


def publish_research(sync, conn, research_id: str) -> str:
    research = conn.execute('SELECT * FROM research_catalog_researches WHERE research_id=?', (research_id,)).fetchone()
    if research is None:
        return ''  # Missing local metadata is never a global deletion.
    owner = str(research['owner_ref'])
    previous = conn.execute(
        'SELECT payload_json FROM account_domain_entities WHERE principal=? AND entity_type=? AND entity_id=?',
        (owner, KIND, research_id),
    ).fetchone()
    prior = json.loads(previous['payload_json']) if previous else {}
    # Do not propagate local-only private Research metadata just because a
    # user created or opened it. Existing shared projections still receive a
    # final revocation update; old private projections are retained without a
    # tombstone and stop receiving new content. Keycloak mode cannot infer a
    # current share from legacy ACL columns and must await its explicit sync
    # contract instead of guessing from them.
    if not getattr(sync, 'research_legacy_sharing', False):
        return ''
    current_shared = _legacy_current_shared(conn, research_id, dict(research))
    prior_shared = bool(previous and _legacy_shared(prior))
    if not (current_shared or prior_shared):
        return ''
    if current_shared:
        value = snapshot(conn, research_id, research_row=research)
    else:
        # Only previously acknowledged content may accompany a withdrawal.
        # The current graph may now contain new private reports or edits.
        base = conn.execute('''SELECT payload_json,deleted FROM account_domain_research_bases
            WHERE principal=? AND entity_id=?''', (owner, research_id)).fetchone()
        if base is None or base['deleted']:
            return ''
        value = json.loads(base['payload_json'])
        if not _legacy_shared(value):
            return ''
        value = {key: value[key] for key in TABLES}
        value['research'] = {**value['research'], 'visibility': 'private', 'authorized_users_json': '[]',
                             'status': str(research['status'])}
        value['members'] = [{**member, 'status': 'revoked'} for member in value['members']]
        value['reports'] = [{**report, 'visibility': 'private', 'authorized_users_json': '[]'}
                            for report in value['reports']]
    payload = public_payload({
        'schema_version': 2, 'visibility': 'public',
        'replication_scope': 'trusted_managers',
        'storage_server_id': prior.get('storage_server_id') or sync.manager_id,
        **({'sharing_scope': 'research'} if current_shared else {}),
        **value,
    })
    operation = sync.local.upsert_local(
        principal=owner, entity_type=KIND, entity_id=research_id,
        payload=payload, manager_id=sync.manager_id, connection=conn,
    )
    if operation and current_shared:
        # An explicit share may make an otherwise identical, formerly private
        # queued snapshot eligible. Reactivate that exact operation atomically
        # with the share rather than leaving it stuck in the repair queue.
        conn.execute('''UPDATE account_domain_outbox SET last_error=''
            WHERE operation_id=? AND last_error='research_sync_needs_review' ''', (operation,))
    if operation and prior_shared and not current_shared:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
        conn.execute('''INSERT OR REPLACE INTO account_domain_research_sync_intents
            (operation_id,principal,entity_id,kind,payload_sha256) VALUES (?,?,?,'revocation',?)''',
            (operation, owner, research_id, hashlib.sha256(encoded).hexdigest()))
    return operation


def research_outbox_status(sync, item: dict) -> str:
    """Return send/review/superseded for one frozen Research outbox item.

    Old private or tombstoned operations are retained for explicit repair,
    never silently dropped or uploaded. A newly recorded final revocation is
    sent only when its exact payload and previous shared revision match.
    Caller holds the per-Research synchronization lock.
    """
    if not getattr(sync, 'research_legacy_sharing', False) or item.get('deleted'):
        return 'review'
    payload = item.get('payload')
    if not isinstance(payload, dict) or payload.get('schema_version') not in {1, 2}:
        return 'review'
    research = payload.get('research')
    if (not isinstance(research, dict) or research.get('research_id') != item.get('entity_id')
            or research.get('owner_ref') != item.get('principal')):
        return 'review'
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    with connect_sqlite(sync.local.path, readonly=True) as conn:
        current = conn.execute('''SELECT payload_json,deleted,base_revision FROM account_domain_outbox
            WHERE operation_id=? AND principal=? AND entity_type=? AND entity_id=?''',
            (item['operation_id'], item['principal'], KIND, item['entity_id'])).fetchone()
        if (current is None or current['payload_json'] != encoded
                or bool(current['deleted']) != bool(item['deleted'])
                or current['base_revision'] != item['base_revision']):
            return 'superseded'
        try:
            live_research = conn.execute('SELECT * FROM research_catalog_researches WHERE research_id=?',
                                         (item['entity_id'],)).fetchone()
            current_shared = (live_research is not None and live_research['owner_ref'] == item['principal']
                              and _legacy_current_shared(conn, item['entity_id'], dict(live_research)))
            live = None
            if current_shared:
                live = snapshot(conn, item['entity_id'], research_row=live_research)
                # Neither an old shared snapshot nor a link snapshot may be
                # sent after its share was revoked or its content changed.
                if live is not None and public_payload(live) == {key: payload.get(key) for key in TABLES}:
                    return 'send'
            intent = conn.execute('''SELECT principal,entity_id,kind,payload_sha256
                FROM account_domain_research_sync_intents WHERE operation_id=?''',
                (item['operation_id'],)).fetchone()
            valid_intent = (intent is not None and intent['principal'] == item['principal']
                            and intent['entity_id'] == item['entity_id']
                            and intent['payload_sha256'] == hashlib.sha256(encoded.encode('utf-8')).hexdigest())
            if valid_intent and str(intent['kind']).startswith('resolution:') and current_shared and _legacy_shared(payload):
                conflict = conn.execute('''SELECT local_payload_json FROM account_domain_conflicts
                    WHERE conflict_id=? AND principal=? AND entity_type=? AND entity_id=?
                    AND status='resolved' AND remote_revision=?''',
                    (str(intent['kind']).removeprefix('resolution:'), item['principal'], KIND,
                     item['entity_id'], current['base_revision'])).fetchone()
                if conflict is not None and live is not None:
                    prior_local = json.loads(conflict['local_payload_json'])
                    if public_payload(live) == {key: prior_local.get(key) for key in TABLES}:
                        return 'send'
            base = conn.execute('''SELECT revision,payload_json,deleted FROM account_domain_research_bases
                WHERE principal=? AND entity_id=?''', (item['principal'], item['entity_id'])).fetchone()
            if (valid_intent and intent['kind'] == 'revocation'
                    and base is not None and not base['deleted'] and current['base_revision'] == base['revision']
                    and _legacy_shared(json.loads(base['payload_json']))):
                return 'send'
        except (TypeError, ValueError, KeyError):
            return 'review'
    return 'review'


def backfill_researches(sync, principal: str) -> int:
    with connect_sqlite(sync.local.path, readonly=True) as conn:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_catalog_researches'").fetchone() is None:
            return 0
        # Existing projections are not re-authored by readers. The write
        # transaction is the only publisher once a Research has an envelope.
        rows = conn.execute('''SELECT research_id FROM research_catalog_researches r
            WHERE owner_ref=? AND migration_source='' AND NOT EXISTS (SELECT 1 FROM account_domain_entities a
                WHERE a.principal=r.owner_ref AND a.entity_type=? AND a.entity_id=r.research_id)''',
            (principal, KIND)).fetchall()
    count = 0
    for row in rows:
        research_id = str(row['research_id'])
        with research_sync_lock(sync.local.path, research_id), connect_sqlite(sync.local.path) as conn:
            conn.execute('BEGIN IMMEDIATE')
            count += bool(publish_research(sync, conn, research_id))
    return count


def materialize_research(database, envelope: dict, *, connection=None) -> None:
    if envelope.get('entity_type') != KIND:
        return
    payload = envelope.get('payload') or {}
    research = payload.get('research') or {}
    identifier = str(envelope['entity_id'])
    revision = int(envelope.get('remote_revision') or envelope.get('revision') or 0)
    if envelope.get('deleted'):
        with (nullcontext(connection) if connection is not None else connect_sqlite(database)) as conn:
            if connection is None:
                conn.execute('BEGIN IMMEDIATE')
                current = conn.execute('SELECT payload_json,remote_revision,deleted FROM account_domain_entities '
                                       'WHERE principal=? AND entity_type=? AND entity_id=?',
                                       (envelope['principal'], KIND, identifier)).fetchone()
                if current is not None and (json.loads(current['payload_json']) != payload
                                            or current['remote_revision'] != revision or not current['deleted']):
                    return
            conn.execute("UPDATE research_catalog_researches SET status='archived' WHERE research_id=? AND owner_ref=?",
                         (identifier, envelope['principal']))
            _record_revision(conn, identifier, revision)
        return
    if (payload.get('schema_version') not in {1, 2} or research.get('research_id') != identifier
            or research.get('owner_ref') != envelope['principal']):
        raise ValueError('invalid research synchronization identity')
    legacy = payload.get('schema_version') == 1
    if legacy:
        payload = {**payload, 'branches': []}
    if any(not isinstance(payload.get(key), list) for key in TABLES if key != 'research'):
        raise ValueError('incomplete research relationship snapshot')
    with (nullcontext(connection) if connection is not None else connect_sqlite(database)) as conn:
        if connection is None:
            conn.execute('BEGIN IMMEDIATE')
        if legacy and conn.execute(
            'SELECT 1 FROM research_catalog_branches WHERE research_id=? LIMIT 1', (identifier,),
        ).fetchone():
            raise ValueError('legacy research snapshot cannot replace registered branches')
        if connection is None:
            current = conn.execute('SELECT payload_json,remote_revision FROM account_domain_entities '
                                   'WHERE principal=? AND entity_type=? AND entity_id=?',
                                   (envelope['principal'], KIND, identifier)).fetchone()
            if current is not None and (json.loads(current['payload_json']) != envelope['payload']
                                        or current['remote_revision'] != revision):
                # The caller's snapshot lost a race to a local edit or a newer
                # pull. Never overwrite the live authoring projection with it.
                return
        # Schema is owned by ResearchCatalog and initialized before sync.
        # An accepted snapshot replaces the relationship projection, including
        # an explicit conflict choice. Otherwise local-only grants survive and
        # concurrent workspace IDs can violate the logical uniqueness key.
        _prune_removed_relationships(conn, identifier, payload)
        reports = {item['report_id'] for item in payload.get('reports', [])}
        for key, (table, primary) in TABLES.items():
            records = [research] if key == 'research' else payload.get(key, [])
            columns = [row['name'] for row in conn.execute(f'PRAGMA table_info({table})')]
            if not columns:
                raise ValueError('research projection schema is unavailable')
            for record in records:
                if key in {'evidence_links', 'branches'}:
                    if record.get('report_id') not in reports or (key == 'branches' and record.get('research_id') != identifier):
                        raise ValueError('research evidence belongs to another report')
                elif record.get('research_id') != identifier:
                    raise ValueError('research relationship belongs to another research')
                if set(record) != set(columns):
                    raise ValueError('incompatible research relationship schema')
                existing = conn.execute(
                    f'SELECT * FROM {table} WHERE ' + ' AND '.join(f'{name}=?' for name in primary),
                    tuple(record[name] for name in primary),
                ).fetchone()
                if existing is not None:
                    identity_fields = ('report_id',) if key == 'evidence_links' else ('research_id',)
                    if key == 'branches':
                        identity_fields += ('principal_ref', 'profile_ref', 'workspace_id', 'source_branch_id',
                                            'source_generation', 'source_revision', 'source_publication_id')
                    if key == 'research':
                        identity_fields += ('owner_ref',)
                    if any(existing[name] != record[name] for name in identity_fields):
                        raise ValueError('research synchronization would replace another identity')
                assignments = ', '.join(f'{name}=excluded.{name}' for name in columns if name not in primary)
                conn.execute(
                    f'INSERT INTO {table} ({", ".join(columns)}) VALUES ({", ".join("?" for _ in columns)}) '
                    f'ON CONFLICT ({", ".join(primary)}) DO UPDATE SET {assignments}',
                    tuple(record[name] for name in columns),
                )
        _record_revision(conn, identifier, revision)


def _prune_removed_relationships(conn, identifier: str, payload: dict) -> None:
    for key, (table, primary) in reversed(tuple(TABLES.items())):
        if key == 'research':
            continue
        retained = {tuple(item[name] for name in primary) for item in payload[key]}
        where = ('report_id IN (SELECT report_id FROM research_catalog_reports WHERE research_id=?)'
                 if key == 'evidence_links' else 'research_id=?')
        existing = conn.execute(
            f'SELECT {", ".join(primary)} FROM {table} WHERE {where}', (identifier,),
        ).fetchall()
        for row in existing:
            identity = tuple(row[name] for name in primary)
            if identity not in retained:
                conn.execute(
                    f'DELETE FROM {table} WHERE ' + ' AND '.join(f'{name}=?' for name in primary),
                    identity,
                )


def _record_revision(conn, identifier: str, revision: int) -> None:
    conn.execute('''INSERT INTO research_catalog_replication VALUES (?, ?)
        ON CONFLICT(research_id) DO UPDATE SET remote_revision=excluded.remote_revision''',
        (identifier, revision))


def materialize_pending_researches(sync) -> int:
    """Also apply explicitly resolved conflicts, without rebuilding hot rows."""
    with connect_sqlite(sync.local.path, readonly=True) as conn:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='research_catalog_replication'").fetchone() is None:
            return 0
        rows = conn.execute('''SELECT a.principal,a.entity_id FROM account_domain_entities a
            LEFT JOIN research_catalog_replication r ON r.research_id=a.entity_id
            WHERE a.entity_type=? AND a.remote_revision IS NOT NULL
              AND (r.remote_revision IS NULL OR r.remote_revision<>a.remote_revision)
              AND NOT EXISTS (SELECT 1 FROM account_domain_outbox o
                  WHERE o.principal=a.principal AND o.entity_type=a.entity_type AND o.entity_id=a.entity_id)''',
            (KIND,)).fetchall()
    for row in rows:
        current = sync.local.get_entity(row['principal'], KIND, row['entity_id'])
        if current is not None:
            materialize_research(sync.local.path, current)
    return len(rows)
