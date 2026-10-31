"""Import one authorized Manager-owned Research into the client catalog."""
from __future__ import annotations

import hashlib
import math
import re
import time
from urllib.parse import quote, urlsplit

from .local_publication import manager_session


def queue_server_researches(store, *, manager: dict, profile_id: str, research_ids: list[str]) -> int:
    profile = store._profile(profile_id)
    if (not isinstance(research_ids, list) or not 1 <= len(research_ids) <= 100
            or any(not isinstance(ref, str) or not re.fullmatch(r'research:v1:[A-Za-z0-9_-]{24,128}', ref) for ref in research_ids)
            or len(set(research_ids)) != len(research_ids)):
        raise ValueError('invalid Research identities')
    if not isinstance(manager, dict) or not isinstance(manager.get('endpoint'), str):
        raise ValueError('native Manager endpoint is invalid')
    endpoint = manager['endpoint'].rstrip('/')
    parsed = urlsplit(endpoint)
    if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment or len(endpoint) > 2048):
        raise ValueError('native Manager endpoint is invalid')
    manager_hash = hashlib.sha256(endpoint.encode()).hexdigest()
    # The durable request contains no credentials. Network or process failure
    # leaves it available for the bounded background synchronizer to retry.
    with store._connect() as db:
        db.execute('BEGIN IMMEDIATE')
        count = db.execute('SELECT count(*) FROM server_research_pending').fetchone()[0]
        added = 0
        for research_id in research_ids:
            present = db.execute('SELECT 1 FROM server_research_pending WHERE research_id=? AND manager_hash=? AND profile_id=?',
                                 (research_id, manager_hash, profile)).fetchone()
            if present:
                continue
            if count + added >= 1000:
                raise ValueError('too many pending Research imports')
            db.execute('INSERT INTO server_research_pending (research_id,manager_hash,profile_id) VALUES (?,?,?)',
                       (research_id, manager_hash, profile))
            added += 1
        return added


def import_server_research(store, *, binding: dict, manager: dict, profile_id: str, research_id: str) -> dict:
    profile = store._profile(profile_id)
    queue_server_researches(store, manager=manager, profile_id=profile, research_ids=[research_id])
    endpoint, session = manager_session(binding, manager)
    manager_hash = hashlib.sha256(endpoint.encode()).hexdigest()
    identity = session.get('/api/session')
    if (str(identity.get('keycloak_issuer') or '').rstrip('/') != binding['issuer']
            or identity.get('tr_identity_id') != binding['identity_id']
            or identity.get('keycloak_subject') != manager['subject']
            or identity.get('visitor_login') is True or identity.get('authentication') == 'agent'
            or not isinstance(identity.get('username'), str) or not identity['username']):
        raise PermissionError('native Manager identity changed')
    response = session.get('/api/research/' + quote(research_id, safe=''))
    value = response.get('research') if response.get('success') is True else None
    if (not isinstance(value, dict) or value.get('research_id') != research_id
            or value.get('owner_ref') != identity['username'] or value.get('is_owned') is not True
            or value.get('status') != 'active' or not isinstance(value.get('access'), dict)
            or value['access'].get('can_view') is not True):
        raise PermissionError('Research ownership or access cannot be verified')
    title, description = value.get('title'), value.get('description')
    created, updated = value.get('created_at'), value.get('updated_at')
    if (not isinstance(title, str) or not title.strip() or len(title) > 256
            or not isinstance(description, str) or len(description) > 10000
            or any(type(item) not in (int, float) or not math.isfinite(item) or item < 0 for item in (created, updated))):
        raise ValueError('Manager Research metadata is invalid')
    # Recheck the exact authenticated principal immediately before a local write.
    current = session.get('/api/session')
    if any(current.get(key) != identity.get(key) for key in ('username', 'keycloak_issuer', 'keycloak_subject', 'tr_identity_id')):
        raise PermissionError('native Manager identity changed')
    latest = session.get('/api/research/' + quote(research_id, safe=''))
    confirmed = latest.get('research') if latest.get('success') is True else None
    if (not isinstance(confirmed, dict) or not isinstance(confirmed.get('access'), dict)
            or confirmed['access'].get('can_view') is not True
            or any(confirmed.get(key) != value.get(key) for key in
                   ('research_id', 'owner_ref', 'is_owned', 'status', 'title', 'description', 'created_at', 'updated_at'))):
        raise PermissionError('Research access or version changed during import')
    operation = 'server-' + hashlib.sha256((manager_hash + '\0' + research_id).encode()).hexdigest()
    with store._connect() as db:
        db.execute('BEGIN IMMEDIATE')
        existing = db.execute('SELECT * FROM researches WHERE research_id=?', (research_id,)).fetchone()
        origin = db.execute('SELECT * FROM server_research_origins WHERE research_id=?', (research_id,)).fetchone()
        if existing is None:
            if origin is not None:
                raise ValueError('local Research origin requires repair')
            db.execute('INSERT INTO researches VALUES (?, ?, ?, ?, ?, ?, ?)',
                       (research_id, profile, title, description, operation, created, updated))
            db.execute('INSERT INTO server_research_origins VALUES (?, ?, ?, ?, ?, ?)',
                       (research_id, manager_hash, profile, title, description, updated))
            status = 'imported'
        else:
            if (origin is None or origin['manager_hash'] != manager_hash or origin['profile_id'] != profile
                    or existing['profile_id'] != profile or existing['created_at'] != created
                    or (existing['title'], existing['description']) != (origin['title'], origin['description'])):
                raise ValueError('local Research conflicts with the Manager copy')
            if updated < origin['updated_at'] or (updated == origin['updated_at'] and (title, description) != (origin['title'], origin['description'])):
                raise ValueError('Manager Research version is inconsistent')
            status = 'unchanged'
            if updated > origin['updated_at']:
                db.execute('UPDATE researches SET title=?,description=?,updated_at=? WHERE research_id=?',
                           (title, description, updated, research_id))
                db.execute('UPDATE server_research_origins SET title=?,description=?,updated_at=? WHERE research_id=?',
                           (title, description, updated, research_id))
                status = 'updated'
        db.execute('DELETE FROM server_research_pending WHERE research_id=? AND manager_hash=? AND profile_id=?',
                   (research_id, manager_hash, profile))
        return {'research': store._public(db.execute('SELECT * FROM researches WHERE research_id=?', (research_id,)).fetchone()),
                'status': status}


def retry_pending_server_research(store, *, binding: dict, manager: dict, profile_id: str, limit: int) -> tuple[list[dict], bool]:
    from tools.cli.http import HttpClientError
    profile = store._profile(profile_id)
    endpoint = str(manager.get('endpoint') or '').rstrip('/')
    manager_hash = hashlib.sha256(endpoint.encode()).hexdigest()
    with store._connect() as db:
        rows = db.execute('''SELECT research_id FROM server_research_pending WHERE manager_hash=? AND profile_id=?
                             ORDER BY last_attempt,research_id LIMIT ?''', (manager_hash, profile, limit)).fetchall()
    result = []
    for row in rows:
        research_id = row['research_id']
        try:
            status = import_server_research(store, binding=binding, manager=manager,
                                            profile_id=profile, research_id=research_id)['status']
        except HttpClientError as exc:
            status = 'denied' if exc.status in {401, 403} else 'unavailable'
        except PermissionError:
            status = 'denied'
        except ValueError:
            status = 'conflict'
        except (OSError, RuntimeError):
            status = 'unavailable'
        if status in {'denied', 'conflict', 'unavailable'}:
            with store._connect() as db:
                db.execute('UPDATE server_research_pending SET last_attempt=? WHERE research_id=? AND manager_hash=? AND profile_id=?',
                           (time.time(), research_id, manager_hash, profile))
        result.append({'research_id': research_id, 'status': status})
    # Drain newly discovered items promptly; failed items wait for the normal
    # retry interval rather than creating a busy loop.
    with store._connect() as db:
        more = db.execute('''SELECT 1 FROM server_research_pending WHERE manager_hash=? AND profile_id=?
                             AND last_attempt=0 LIMIT 1''', (manager_hash, profile)).fetchone() is not None
    return result, more
