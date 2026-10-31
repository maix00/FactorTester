"""Explicit, session-bound publication of one local report to a Manager."""
from __future__ import annotations

import base64
import hashlib
import json
import re
from urllib.parse import urlsplit

from tools.cli.http import HttpSession
from .authoring.tree_paths import report_tree_paths
from .authoring.tree_bundle import bundle_from_snapshot
from .authoring.tree_projection import project_snapshot
from .authoring.tree_store import load_head, tree_lock
from .generation import report_workspace_lock
from .public_research.projection import build_upload_projection
from .report_workspace_identity import report_workspace_id_for


def publish_local_report(store, *, binding: dict, manager: dict, profile_id: str,
                         research_id: str, report_id: str) -> dict:
    if not isinstance(manager, dict) or set(manager) != {'endpoint', 'token', 'certificate_pem', 'cookies'}:
        raise ValueError('native Manager transport is invalid')
    endpoint, token, certificate, cookies = (manager[key] for key in ('endpoint', 'token', 'certificate_pem', 'cookies'))
    if not all(isinstance(value, str) for value in (endpoint, token, certificate)) or not isinstance(cookies, list):
        raise ValueError('native Manager transport is invalid')
    parsed = urlsplit(endpoint)
    if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in {'', '/'} or parsed.query or parsed.fragment or len(endpoint) > 2048):
        raise ValueError('native Manager endpoint is invalid')
    endpoint = endpoint.rstrip('/')
    if any(not isinstance(cookie, dict) or cookie.get('name') != 'ft-manager-session' for cookie in cookies):
        raise ValueError('native Manager cookies are invalid')
    session = HttpSession(endpoint, bearer_token=token, certificate_pem=certificate, persist_cookies=False)
    session.import_cookies(cookies)
    current = session.get('/api/session')
    if (str(current.get('keycloak_issuer') or '').rstrip('/') != binding['issuer']
            or current.get('tr_identity_id') != binding['identity_id'] or not current.get('keycloak_subject')):
        raise PermissionError('native Manager identity changed')

    _report, root = store._report_root(profile_id, research_id, report_id)
    manager_hash = hashlib.sha256(endpoint.encode()).hexdigest()
    lock = store.workspace_root / '.locks' / ('publication-' + report_workspace_id_for(report_id) + '-' + manager_hash[:16])
    with report_workspace_lock(lock):
        paths = report_tree_paths(root, 'main')
        with tree_lock(paths):
            head = load_head(paths)
            if head['report_id'] != report_id:
                raise ValueError('local report identity is invalid')
            snapshot = project_snapshot(paths, head)
            projection = build_upload_projection(snapshot)
            bundle = bundle_from_snapshot(snapshot, package_root=root, branch_id='main')
        if not bundle or len(bundle) > 8 * 1024 * 1024:
            raise ValueError('report authoring bundle exceeds Manager limit')
        authoring = {'sha256': hashlib.sha256(bundle).hexdigest(), 'root_ref': head['root_ref'],
                     'content_base64': base64.b64encode(bundle).decode('ascii')}
        # Match the existing Manager request budget, before making a network call.
        encoded_size = len(json.dumps({'projection': projection, 'authoring': authoring}, ensure_ascii=False).encode('utf-8'))
        if encoded_size > 30 * 1024 * 1024:
            raise ValueError('report publication exceeds Manager request limit')
        with store._connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS report_publications (
                report_id TEXT NOT NULL, manager_hash TEXT NOT NULL, publication_id TEXT NOT NULL,
                revision TEXT NOT NULL, generation INTEGER NOT NULL, projection_hash TEXT NOT NULL,
                PRIMARY KEY(report_id, manager_hash))''')
            row = db.execute('SELECT revision FROM report_publications WHERE report_id=? AND manager_hash=?',
                             (report_id, manager_hash)).fetchone()
            expected_revision = row['revision'] if row else None
        response = session.post('/api/research/local-report-publication', {'research_id': research_id,
            'report_id': report_id, 'branch_ref': 'main', 'projection': projection, 'authoring': authoring,
            'expected_revision': expected_revision})
        value = response.get('publication') if response.get('success') is True else None
        if (not isinstance(value, dict) or value.get('report_id') != report_id
                or not re.fullmatch(r'p-[0-9a-f]{64}', str(value.get('publication_id') or ''))
                or not isinstance(value.get('revision'), str) or not value['revision'] or len(value['revision']) > 256
                or value.get('generation') != head['generation']
                or not re.fullmatch(r'[0-9a-f]{64}', str(value.get('projection_hash') or ''))):
            raise ValueError('Manager publication receipt is invalid')
        with store._connect() as db:
            db.execute('''INSERT INTO report_publications VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(report_id, manager_hash) DO UPDATE SET publication_id=excluded.publication_id,
                revision=excluded.revision, generation=excluded.generation, projection_hash=excluded.projection_hash''',
                (report_id, manager_hash, value['publication_id'], value['revision'], value['generation'], value['projection_hash']))
        return {'publication': {key: value[key] for key in ('publication_id', 'revision', 'generation', 'projection_hash', 'report_id')}}
