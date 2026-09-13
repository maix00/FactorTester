"""SQLite storage for server-registered user factor sets."""

from __future__ import annotations

import json
import sqlite3
import time
import os
import uuid
import hashlib
from typing import Any

import settings as Settings
from tools.data.sqlite.db import connect_sqlite


def ensure_factor_set_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS account_factor_sets (
            username TEXT NOT NULL,
            target_ref TEXT NOT NULL,
            owner_ref TEXT NOT NULL,
            set_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (username, target_ref)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_account_factor_sets_owner_name
        ON account_factor_sets (username, owner_ref, set_id, updated_at DESC)
        """
    )


def list_factor_sets(username: str) -> list[dict[str, Any]]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_factor_set_schema(conn)
        rows = conn.execute(
            """
            SELECT payload_json
            FROM account_factor_sets
            WHERE username = ?
            ORDER BY updated_at DESC, target_ref
            """,
            (username,),
        ).fetchall()
    values = [
        value for row in rows
        if isinstance((value := _payload(row["payload_json"])), dict)
    ]
    from tools.data.sqlite.account_manager.domain_sync import overlay_entities
    values = overlay_entities(username, 'factor_set', values, id_key='ref')
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        return _current_values(conn, username, values)


def get_factor_set(username: str, target_ref: str) -> dict[str, Any] | None:
    from server.manager.storage.account_domain.local import LocalAccountDomainStore
    mirrored = LocalAccountDomainStore(Settings.CACHE_DB_PATH).get_entity(username, 'factor_set', target_ref)
    if mirrored is not None:
        return None if mirrored['deleted'] else mirrored['payload']
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_factor_set_schema(conn)
        row = conn.execute(
            """
            SELECT payload_json
            FROM account_factor_sets
            WHERE username = ? AND target_ref = ?
            """,
            (username, target_ref),
        ).fetchone()
    return _payload(row["payload_json"]) if row is not None else None


def _visible_sets(conn, username):
    values = {row['target_ref']: json.loads(row['payload_json']) for row in conn.execute(
        'SELECT target_ref,payload_json FROM account_factor_sets WHERE username=?', (username,))}
    for row in conn.execute("SELECT entity_id,payload_json,deleted FROM account_domain_entities WHERE principal=? AND entity_type='factor_set'", (username,)):
        if row['deleted']:
            values.pop(row['entity_id'], None)
        else:
            values[row['entity_id']] = json.loads(row['payload_json'])
    return values


def _head_id(value):
    return hashlib.sha256(json.dumps([value['owner_ref'],value['identity']['set_id']],
        separators=(',',':')).encode()).hexdigest()


def _current_values(conn, username, values):
    tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    heads={}
    if 'account_domain_entities' in tables:
        heads={r['entity_id']:json.loads(r['payload_json']) for r in conn.execute(
            "SELECT entity_id,payload_json FROM account_domain_entities WHERE principal=? AND entity_type='factor_set_head' AND NOT deleted",(username,))}
    return [v for v in values if v.get('registration_active',True)
        and (_head_id(v) not in heads or (heads[_head_id(v)].get('active')
             and heads[_head_id(v)].get('ref')==v['ref']))]


def _set_head(conn, mirror, username, value, *, active=True):
    mirror.upsert_local(principal=username,entity_type='factor_set_head',entity_id=_head_id(value),
        payload={'owner_ref':value['owner_ref'],'set_id':value['identity']['set_id'],
                 'ref':value['ref'],'active':active},connection=conn,
        manager_id=os.environ.get('FACTORTESTER_SERVER_ID') or 'local')


def _persist(conn, mirror, username, payload):
    from server.manager.storage.account_domain.payloads import public_payload
    payload = public_payload(payload)
    conn.execute("""INSERT INTO account_factor_sets
        (username,target_ref,owner_ref,set_id,payload_json,updated_at) VALUES(?,?,?,?,?,?)
        ON CONFLICT(username,target_ref) DO UPDATE SET payload_json=excluded.payload_json,
        updated_at=excluded.updated_at""", (username, payload['ref'], payload['owner_ref'],
        payload['identity']['set_id'], json.dumps(payload, ensure_ascii=False), payload['updated_at']))
    mirror.upsert_local(principal=username, entity_type='factor_set', entity_id=payload['ref'],
        payload=payload, manager_id=os.environ.get('FACTORTESTER_SERVER_ID') or 'local', connection=conn)


def _events(conn, mirror, username, value, old_members, new_members, reason):
    before = {m['ref']: m for m in old_members}
    after = {m['ref']: m for m in new_members}
    operation = uuid.uuid4().hex
    for action, members in [('removed', [before[r] for r in before.keys()-after.keys()]),
                            ('added', [after[r] for r in after.keys()-before.keys()])]:
        for member in sorted(members, key=lambda m: m['ref']):
            event_id = uuid.uuid4().hex
            payload = {'set_owner_ref': value['owner_ref'], 'set_id': value['identity']['set_id'],
                'set_ref': value['ref'], 'operation_id': operation, 'event_id': event_id,
                'action': action, 'member': member, 'reason': reason, 'occurred_at': time.time()}
            mirror.upsert_local(principal=username, entity_type='factor_set_event', entity_id=event_id,
                payload=payload, manager_id=os.environ.get('FACTORTESTER_SERVER_ID') or 'local', connection=conn)


def save_factor_set(username: str, value: dict[str, Any], *, reason='edit') -> dict[str, Any]:
    from tools.factors.factor_set_identity import require_frozen_factor_set
    from server.manager.storage.account_domain.local import LocalAccountDomainStore
    require_frozen_factor_set(value)
    payload = {**value, 'registration_active': True, 'updated_at': time.time()}
    mirror = LocalAccountDomainStore(Settings.CACHE_DB_PATH)
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_factor_set_schema(conn)
        conn.execute('BEGIN IMMEDIATE')
        previous = [v for v in _current_values(conn, username, _visible_sets(conn, username).values())
            if v.get('registration_active', True) and v['owner_ref'] == value['owner_ref']
            and v['identity']['set_id'] == value['identity']['set_id']]
        if len(previous) > 1:
            raise ValueError('集合存在多个当前版本，请先处理版本冲突')
        old = previous[0] if previous else None
        if old and old['ref'] != value['ref']:
            _persist(conn, mirror, username, {**old, 'registration_active': False, 'updated_at': time.time()})
        _persist(conn, mirror, username, payload)
        _set_head(conn, mirror, username, payload)
        _events(conn, mirror, username, payload, (old or {}).get('identity', {}).get('members', []),
                payload['identity']['members'], reason)
    return payload


def delete_factor_set(username: str, target_ref: str) -> bool:
    from server.manager.storage.account_domain.local import LocalAccountDomainStore
    mirror = LocalAccountDomainStore(Settings.CACHE_DB_PATH)
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_factor_set_schema(conn)
        conn.execute('BEGIN IMMEDIATE')
        value = _visible_sets(conn, username).get(target_ref)
        if not value or not value.get('registration_active', True):
            return False
        _persist(conn, mirror, username, {**value, 'registration_active': False, 'updated_at': time.time()})
        _set_head(conn, mirror, username, value, active=False)
        _events(conn, mirror, username, value, value['identity']['members'], [], 'unregister')
    return True


def factor_set_history(username, target_ref, *, offset=0, limit=50):
    value = get_factor_set(username, target_ref)
    if value is None:
        return None
    offset, limit = max(0, int(offset)), min(100, max(1, int(limit)))
    with connect_sqlite(Settings.CACHE_DB_PATH, readonly=True) as conn:
        rows = conn.execute("""SELECT payload_json FROM account_domain_entities
            WHERE principal=? AND entity_type='factor_set_event' AND NOT deleted
            AND json_extract(payload_json,'$.set_owner_ref')=?
            AND json_extract(payload_json,'$.set_id')=?
            ORDER BY json_extract(payload_json,'$.occurred_at') DESC, entity_id DESC
            LIMIT ? OFFSET ?""", (username,value['owner_ref'],value['identity']['set_id'],limit+1,offset)).fetchall()
    return {'items': [json.loads(r['payload_json']) for r in rows[:limit]],
            'has_more': len(rows)>limit, 'next_offset': offset+min(len(rows),limit)}


def _payload(raw: str) -> dict[str, Any] | None:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None

def historical_factor(username, target_ref, factor_ref):
    """Resolve only members of this user's stored set lineage, never client JSON."""
    value = get_factor_set(username, target_ref)
    if value is None:
        return None
    for member in value['identity']['members']:
        if member['ref'] == factor_ref:
            return member
    with connect_sqlite(Settings.CACHE_DB_PATH, readonly=True) as conn:
        row = conn.execute("""SELECT payload_json FROM account_domain_entities
            WHERE principal=? AND entity_type='factor_set_event' AND NOT deleted
            AND json_extract(payload_json,'$.set_owner_ref')=?
            AND json_extract(payload_json,'$.set_id')=?
            AND json_extract(payload_json,'$.member.ref')=? LIMIT 1""",
            (username,value['owner_ref'],value['identity']['set_id'],factor_ref)).fetchone()
    return json.loads(row['payload_json'])['member'] if row else None
