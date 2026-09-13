"""Bounded Research relationship projections for trusted Manager replicas.

The replication envelope is cluster-visible so revocations reach replicas that
previously cached a grant. It is not a public Research grant: all user-facing
reads must use ResearchCatalog's nested visibility/membership access policy.
No HTTP endpoint exposes this envelope or the account-domain store directly.
Report bytes and share-link capabilities are deliberately absent.
"""
from __future__ import annotations

import json
from contextlib import nullcontext

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


def snapshot(conn, research_id: str) -> dict | None:
    row = conn.execute('SELECT * FROM research_catalog_researches WHERE research_id=?', (research_id,)).fetchone()
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


def publish_research(sync, conn, research_id: str) -> str:
    value = snapshot(conn, research_id)
    if value is None:
        return ''  # Missing local metadata is never a global deletion.
    owner = value['research']['owner_ref']
    previous = conn.execute(
        'SELECT payload_json FROM account_domain_entities WHERE principal=? AND entity_type=? AND entity_id=?',
        (owner, KIND, research_id),
    ).fetchone()
    prior = json.loads(previous['payload_json']) if previous else {}
    payload = public_payload({
        'schema_version': 2, 'visibility': 'public',
        'replication_scope': 'trusted_managers',
        'storage_server_id': prior.get('storage_server_id') or sync.manager_id,
        **value,
    })
    return sync.local.upsert_local(
        principal=owner, entity_type=KIND, entity_id=research_id,
        payload=payload, manager_id=sync.manager_id, connection=conn,
    )


def backfill_researches(sync, principal: str) -> int:
    with connect_sqlite(sync.local.path) as conn:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_catalog_researches'").fetchone() is None:
            return 0
        # Existing projections are not re-authored by readers. The write
        # transaction is the only publisher once a Research has an envelope.
        rows = conn.execute('''SELECT research_id FROM research_catalog_researches r
            WHERE owner_ref=? AND migration_source='' AND NOT EXISTS (SELECT 1 FROM account_domain_entities a
                WHERE a.principal=r.owner_ref AND a.entity_type=? AND a.entity_id=r.research_id)''',
            (principal, KIND)).fetchall()
        for row in rows:
            publish_research(sync, conn, row['research_id'])
        return len(rows)


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
