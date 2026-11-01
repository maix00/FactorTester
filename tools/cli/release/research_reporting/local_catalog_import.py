"""Import one editable Manager-owned report with a recoverable local receipt."""
from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

from .authoring.tree_bundle import import_report_bundle
from .authoring.tree_projection import load_snapshot
from .generation import report_workspace_lock
from .git import commit_report_workspace
from .local_publication import ensure_publication_table, manager_session, publication_endpoint
from .local_pull import LocalReportSyncConflict, _remote
from .public_research.object_uploads import detach_object_bytes, projection_hash
from .public_research.projection import build_upload_projection
from .report_workspace_identity import report_workspace_id_for


def _tree(root: Path) -> str:
    status = subprocess.run(['git', '-C', str(root), 'status', '--porcelain'], capture_output=True, text=True, check=True)
    if status.stdout.strip():
        raise LocalReportSyncConflict('report workspace has uncommitted changes')
    return subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD^{tree}'], text=True).strip()


def _require_owned_research(session, research_id: str, owner: str) -> None:
    value = session.get('/api/research/' + quote(research_id, safe=''))
    research = value.get('research') if value.get('success') is True else None
    if (not isinstance(research, dict) or research.get('research_id') != research_id
            or research.get('owner_ref') != owner or research.get('is_owned') is not True
            or research.get('status') != 'active' or not isinstance(research.get('access'), dict)
            or research['access'].get('can_view') is not True):
        raise PermissionError('Research ownership or access cannot be verified')


def import_catalog_report(store, *, binding: dict, manager: dict, profile_id: str,
                          research_id: str, report_id: str) -> dict:
    """Import an owned catalog report; never replace an existing local workspace."""
    profile = store._profile(profile_id)
    root_id = report_workspace_id_for(report_id)
    endpoint, session = manager_session(binding, manager)
    identity = session.get('/api/session')
    manager_hash = hashlib.sha256(endpoint.encode()).hexdigest()
    with store._connect() as db:
        origin = db.execute('SELECT * FROM server_research_origins WHERE research_id=?', (research_id,)).fetchone()
    if not origin or origin['manager_hash'] != manager_hash or origin['profile_id'] != profile:
        raise PermissionError('owned Manager Research must be imported first')
    _require_owned_research(session, research_id, identity.get('username'))
    ensure_publication_table(store)
    metadata = _remote(session, research_id, report_id, metadata_only=True, requires_edit=True, source_kind='catalog')
    remote = _remote(session, research_id, report_id, source_kind='catalog')
    record, bundle = remote['publication'], remote['authoring']
    if (metadata != {'publication': record, 'authoring': bundle}
            or record.get('owner_ref') != identity.get('username')):
        raise PermissionError('report owner or version cannot be verified')
    title = record.get('title')
    if not isinstance(title, str) or not title.strip() or len(title) > 256:
        raise ValueError('remote report title is invalid')
    if store.workspace_root.is_symlink():
        raise ValueError('local report directory cannot be a symlink')
    store.workspace_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent = store.workspace_root / 'research'
    if parent.is_symlink():
        raise ValueError('local report directory cannot be a symlink')
    parent.mkdir(mode=0o700, exist_ok=True)
    target = parent / root_id
    lock = store.workspace_root / '.locks' / root_id
    with report_workspace_lock(lock):
        with store._connect() as db:
            existing = db.execute('SELECT * FROM reports WHERE report_id=?', (report_id,)).fetchone()
            receipt = db.execute('SELECT * FROM report_publications WHERE report_id=? AND manager_hash=?',
                                 (report_id, manager_hash)).fetchone()
        if existing and existing['ready']:
            if (existing['profile_id'] != profile or existing['research_id'] != research_id or not receipt
                    or receipt['source_kind'] != 'catalog' or receipt['publication_id'] != record['publication_id']):
                raise LocalReportSyncConflict('local report already has another origin')
            return {'status': 'already_imported', 'report': store._report_public(existing)}
        if existing:
            raise LocalReportSyncConflict('local report reservation belongs to another operation')
        response = session.download(publication_endpoint('catalog', research_id, report_id)
            + '/' + record['publication_id'] + '/attachments/report_authoring/' + bundle['sha256'], maximum_bytes=8 * 1024 * 1024)
        if len(response.content) != bundle['size_bytes'] or hashlib.sha256(response.content).hexdigest() != bundle['sha256']:
            raise ValueError('remote report bundle checksum or size mismatch')
        with tempfile.TemporaryDirectory(prefix='catalog-import-', dir=store.workspace_root) as temporary:
            staged = Path(temporary) / root_id
            imported = import_report_bundle(payload=response.content, expected_sha256=bundle['sha256'], package_root=staged,
                branch_id='main', report_id=report_id, source_generation=bundle['generation'], source_root_ref=bundle['root_ref'])
            # The projection and authoring bundle are separately validated by the
            # server. Compare their content before accepting either as the baseline.
            projection, _uploads = detach_object_bytes(build_upload_projection(load_snapshot(package_root=staged, branch_id='main')))
            projection['updated_at'] = remote['projection']['updated_at']
            if projection_hash(projection) != record['projection_hash']:
                raise LocalReportSyncConflict('report source and published projection differ')
            commit_report_workspace(staged, message='Import report from Manager')
            staged_tree = _tree(staged)
            confirmed = _remote(session, research_id, report_id, metadata_only=True, requires_edit=True, source_kind='catalog')
            current = session.get('/api/session')
            _require_owned_research(session, research_id, identity.get('username'))
            if (confirmed != metadata or any(current.get(key) != identity.get(key) for key in
                    ('username', 'keycloak_issuer', 'keycloak_subject', 'tr_identity_id'))):
                raise PermissionError('report authorization or version changed during import')
            # If a process died after rename but before SQLite commit, accept only
            # the exact clean Git tree rebuilt from the still-authorized source.
            if target.exists() or target.is_symlink():
                if target.is_symlink() or not target.is_dir() or _tree(target) != staged_tree:
                    raise LocalReportSyncConflict('existing report workspace differs from Manager source')
            else:
                os.rename(staged, target)
            operation = 'server-report-' + hashlib.sha256((manager_hash + '\0' + report_id).encode()).hexdigest()
            with store._connect() as db:
                db.execute('BEGIN IMMEDIATE')
                if db.execute('SELECT 1 FROM reports WHERE report_id=? OR operation_id=?', (report_id, operation)).fetchone():
                    raise LocalReportSyncConflict('local report changed during import')
                db.execute('INSERT INTO reports VALUES (?, ?, ?, ?, ?, ?, 1)',
                           (report_id, research_id, profile, title, operation, time.time()))
                db.execute('''INSERT INTO report_publications (report_id,manager_hash,publication_id,revision,generation,
                    projection_hash,local_root_ref,source_kind) VALUES (?,?,?,?,?,?,?,?)''',
                    (report_id, manager_hash, record['publication_id'], record['revision'], record['generation'],
                     record['projection_hash'], imported['head']['root_ref'], 'catalog'))
                row = db.execute('SELECT * FROM reports WHERE report_id=?', (report_id,)).fetchone()
            return {'status': 'imported', 'report': store._report_public(row)}
