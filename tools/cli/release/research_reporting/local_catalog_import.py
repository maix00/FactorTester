"""Import one editable Manager-owned report with a recoverable local receipt."""
from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import quote, urlencode

from .authoring.tree_bundle import import_report_bundle
from .generation import report_workspace_lock
from .git import commit_report_workspace
from .local_publication import ensure_publication_table, manager_session, publication_endpoint, publication_query
from .local_pull import LocalReportSyncConflict, _remote
from .local_projection_validation import bundle_matches_projection
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
    return _import_report(store, binding=binding, manager=manager, profile_id=profile_id,
                          research_id=research_id, report_id=report_id, source_kind='catalog')


def import_shared_local_report(store, *, binding: dict, manager: dict, profile_id: str,
                               research_id: str, report_id: str) -> dict:
    """Restore an explicitly shared local report owned by this identity."""
    return _import_report(store, binding=binding, manager=manager, profile_id=profile_id,
                          research_id=research_id, report_id=report_id, source_kind='local')


def _owner_metadata(session, research_id, report_id, metadata):
    value = session.get(publication_endpoint('local', research_id, report_id), query={
        **publication_query('local', research_id, report_id), 'branch_ref': 'main',
        'metadata_only': '1', 'requires_edit': '1', 'owner_metadata': '1'})
    owner = value.get('owner_metadata')
    if (value.get('success') is not True or value.get('edit_authorized') is not True
            or value.get('publication') != metadata['publication'] or value.get('authoring') != metadata['authoring']
            or not isinstance(owner, dict) or set(owner) != {'research_title', 'revision'}
            or not isinstance(owner['revision'], str) or not owner['revision']):
        raise PermissionError('shared report owner metadata cannot be verified')
    title = owner['research_title']
    if not isinstance(title, str) or not title.strip() or len(title) > 256 or '\x00' in title:
        raise LocalReportSyncConflict('shared Research metadata requires repair')
    return owner


def verify_equivalent_authoring(store, *, root, head, remote, session, research_id, report_id, source_kind):
    """Compare complete bounded editable content, including assets and private links."""
    from .authoring.tree_bundle import bundle_from_snapshot, validate_report_bundle
    from .authoring.tree_paths import report_tree_paths
    from .authoring.tree_projection import project_snapshot
    from .authoring.tree_store import load_head, tree_lock

    record, bundle = remote['publication'], remote['authoring']
    paths = report_tree_paths(root, 'main')
    with tree_lock(paths):
        current = load_head(paths)
        if (current['report_id'], current['generation'], current['root_ref']) != (report_id, head['generation'], head['root_ref']):
            raise LocalReportSyncConflict('local report changed during comparison')
        if (head['report_id'], head['generation']) != (report_id, bundle['generation']):
            raise LocalReportSyncConflict('local and Manager report versions differ')
        data = bundle_from_snapshot(project_snapshot(paths, head), package_root=root, branch_id='main')
    local_sha = hashlib.sha256(data).hexdigest()
    local_manifest, _local_files = validate_report_bundle(payload=data, expected_sha256=local_sha, report_id=report_id,
        source_generation=head['generation'], source_root_ref=head['root_ref'])
    del _local_files
    if len(data) == bundle['size_bytes'] and local_sha == bundle['sha256']:
        manifest, _files = validate_report_bundle(payload=data, expected_sha256=bundle['sha256'], report_id=report_id,
            source_generation=bundle['generation'], source_root_ref=bundle['root_ref'])
        del data, _files
    else:
        # Imports rewrite local asset paths and transient head metadata, so
        # equivalent reports need not have byte-identical ZIPs or root refs.
        # Validate the remote bundle and both source-free projections before
        # accepting that equivalence. Keep all temporary bytes bounded.
        del data
        attachment = publication_endpoint(source_kind, research_id, report_id) + '/' + record['publication_id'] + '/attachments/report_authoring/' + bundle['sha256']
        query = urlencode(publication_query(source_kind, research_id, report_id))
        response = session.download(attachment + ('?' + query if query else ''), maximum_bytes=8 * 1024 * 1024)
        if len(response.content) != bundle['size_bytes'] or hashlib.sha256(response.content).hexdigest() != bundle['sha256']:
            raise LocalReportSyncConflict('Manager report source bytes differ')
        with tempfile.TemporaryDirectory(prefix='report-attach-', dir=store.workspace_root) as temporary:
            staged = Path(temporary) / 'report'
            imported = import_report_bundle(payload=response.content, expected_sha256=bundle['sha256'], package_root=staged,
                branch_id='main', report_id=report_id, source_generation=bundle['generation'],
                source_root_ref=bundle['root_ref'], restore_artifacts=False)
            manifest = imported['source_manifest']
            del imported  # No Job artifacts are installed for this comparison.
            if manifest.get('source_branch_id') != 'main':
                raise LocalReportSyncConflict('Manager report source branch differs')
            if not bundle_matches_projection(package_root=staged, source_manifest=manifest,
                    remote_projection=remote['projection'], expected_hash=record['projection_hash']):
                raise LocalReportSyncConflict('Manager report source and projection differ')
            staged_paths = report_tree_paths(staged, 'main')
            with tree_lock(staged_paths):
                staged_head = load_head(staged_paths)
                staged_data = bundle_from_snapshot(project_snapshot(staged_paths, staged_head),
                                                   package_root=staged, branch_id='main')
            staged_manifest, _staged_files = validate_report_bundle(payload=staged_data,
                expected_sha256=hashlib.sha256(staged_data).hexdigest(), report_id=report_id,
                source_generation=staged_head['generation'], source_root_ref=staged_head['root_ref'])
            del staged_data, _staged_files
            # This field only invalidates a local rendering cache; importing a
            # bundle resets it to root. All other authoring metadata, nodes,
            # asset identities and object hashes must agree exactly.
            local_manifest['head'].pop('changed_node_ids')
            staged_manifest['head'].pop('changed_node_ids')
            if local_manifest != staged_manifest:
                raise LocalReportSyncConflict('local and Manager editable report trees differ')
        del response
    if not bundle_matches_projection(package_root=root, source_manifest=manifest,
                                     remote_projection=remote['projection'], expected_hash=record['projection_hash']):
        raise LocalReportSyncConflict('local report and Manager projection differ')
    return local_sha


def _attach_identical_shared_report(store, *, root, existing, metadata, remote, owner_metadata,
                                    session, identity, research_id, report_id, manager_hash):
    """Attach a second Manager only when the editable report content agrees."""
    from .authoring.tree_bundle import bundle_from_snapshot
    from .authoring.tree_paths import report_tree_paths
    from .authoring.tree_projection import project_snapshot
    from .authoring.tree_store import load_head, tree_lock

    record = remote['publication']
    if root.is_symlink() or not root.is_dir():
        raise LocalReportSyncConflict('local report workspace is unavailable')
    _tree(root)
    paths = report_tree_paths(root, 'main')
    with tree_lock(paths):
        head = load_head(paths)
    local_sha = verify_equivalent_authoring(store, root=root, head=head, remote=remote, session=session,
        research_id=research_id, report_id=report_id, source_kind='local')
    confirmed = _remote(session, research_id, report_id, metadata_only=True, requires_edit=True, source_kind='local')
    current = session.get('/api/session')
    if (confirmed != metadata or _owner_metadata(session, research_id, report_id, confirmed) != owner_metadata
            or any(current.get(key) != identity.get(key) for key in
                   ('username', 'keycloak_issuer', 'keycloak_subject', 'tr_identity_id'))):
        raise PermissionError('report authorization or version changed during attachment')
    with tree_lock(paths):
        current_head = load_head(paths)
        if (current_head['generation'], current_head['root_ref']) != (head['generation'], head['root_ref']):
            raise LocalReportSyncConflict('local report changed during attachment')
        # Assets are outside the immutable tree and can change independently.
        current_data = bundle_from_snapshot(project_snapshot(paths, current_head), package_root=root, branch_id='main')
        if hashlib.sha256(current_data).hexdigest() != local_sha:
            raise LocalReportSyncConflict('local report assets changed during attachment')
        with store._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM reports WHERE report_id=?', (report_id,)).fetchone()
            if (row is None or row['ready'] != 1 or row['research_id'] != existing['research_id']
                    or row['profile_id'] != existing['profile_id']):
                raise LocalReportSyncConflict('local report identity changed during attachment')
            if db.execute('SELECT 1 FROM report_publications WHERE report_id=? AND manager_hash=?',
                          (report_id, manager_hash)).fetchone():
                raise LocalReportSyncConflict('Manager receipt changed during attachment')
            db.execute('''INSERT INTO report_publications (report_id,manager_hash,publication_id,revision,generation,
                projection_hash,local_root_ref,source_kind) VALUES (?,?,?,?,?,?,?,?)''',
                (report_id, manager_hash, record['publication_id'], record['revision'], record['generation'],
                 record['projection_hash'], head['root_ref'], 'local'))
        from .local_sync_baseline import write_baseline
        write_baseline(store, report_id=report_id, manager_hash=manager_hash,
            receipt={**record, 'local_root_ref': head['root_ref']}, content_sha256=local_sha)
    return {'status': 'attached', 'report': store._report_public(existing)}


def _import_report(store, *, binding, manager, profile_id, research_id, report_id, source_kind):
    profile = store._profile(profile_id)
    root_id = report_workspace_id_for(report_id)
    endpoint, session = manager_session(binding, manager)
    identity = session.get('/api/session')
    manager_hash = hashlib.sha256(endpoint.encode()).hexdigest()
    if source_kind == 'catalog':
        with store._connect() as db:
            origin = db.execute('SELECT * FROM server_research_origins WHERE research_id=?', (research_id,)).fetchone()
        if not origin or origin['manager_hash'] != manager_hash or origin['profile_id'] != profile:
            raise PermissionError('owned Manager Research must be imported first')
        _require_owned_research(session, research_id, identity.get('username'))
    ensure_publication_table(store)
    metadata = _remote(session, research_id, report_id, metadata_only=True, requires_edit=True, source_kind=source_kind)
    owner_metadata = _owner_metadata(session, research_id, report_id, metadata) if source_kind == 'local' else None
    remote = _remote(session, research_id, report_id, source_kind=source_kind)
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
            parent = db.execute('SELECT profile_id FROM researches WHERE research_id=?', (research_id,)).fetchone()
        if source_kind == 'local' and parent is not None and parent['profile_id'] != profile:
            raise LocalReportSyncConflict('local Research belongs to another profile')
        if existing and existing['ready']:
            if existing['profile_id'] != profile or existing['research_id'] != research_id:
                raise LocalReportSyncConflict('local report already has another origin')
            if not receipt and source_kind == 'local':
                return _attach_identical_shared_report(store, root=target, existing=existing, metadata=metadata,
                    remote=remote, owner_metadata=owner_metadata, session=session, identity=identity,
                    research_id=research_id, report_id=report_id, manager_hash=manager_hash)
            if (not receipt or receipt['source_kind'] != source_kind
                    or receipt['publication_id'] != record['publication_id']):
                raise LocalReportSyncConflict('local report already has another origin')
            return {'status': 'already_imported', 'report': store._report_public(existing)}
        if existing:
            raise LocalReportSyncConflict('local report reservation belongs to another operation')
        attachment = publication_endpoint(source_kind, research_id, report_id) + '/' + record['publication_id'] + '/attachments/report_authoring/' + bundle['sha256']
        query = publication_query(source_kind, research_id, report_id)
        response = session.download(attachment + ('?' + urlencode(query) if query else ''), maximum_bytes=8 * 1024 * 1024)
        if len(response.content) != bundle['size_bytes'] or hashlib.sha256(response.content).hexdigest() != bundle['sha256']:
            raise ValueError('remote report bundle checksum or size mismatch')
        with tempfile.TemporaryDirectory(prefix='catalog-import-', dir=store.workspace_root) as temporary:
            staged = Path(temporary) / root_id
            imported = import_report_bundle(payload=response.content, expected_sha256=bundle['sha256'], package_root=staged,
                branch_id='main', report_id=report_id, source_generation=bundle['generation'], source_root_ref=bundle['root_ref'],
                restore_artifacts=False)
            # The projection and authoring bundle are separately validated by the
            # server. Compare their content before accepting either as the baseline.
            if not bundle_matches_projection(package_root=staged,
                    source_manifest=imported['source_manifest'],
                    remote_projection=remote['projection'], expected_hash=record['projection_hash']):
                raise LocalReportSyncConflict('report source and published projection differ')
            commit_report_workspace(staged, message='Import report from Manager')
            staged_tree = _tree(staged)
            confirmed = _remote(session, research_id, report_id, metadata_only=True, requires_edit=True, source_kind=source_kind)
            current = session.get('/api/session')
            if source_kind == 'catalog':
                _require_owned_research(session, research_id, identity.get('username'))
            elif _owner_metadata(session, research_id, report_id, confirmed) != owner_metadata:
                raise PermissionError('shared Research metadata changed during import')
            if (confirmed != metadata or any(current.get(key) != identity.get(key) for key in
                    ('username', 'keycloak_issuer', 'keycloak_subject', 'tr_identity_id'))):
                raise PermissionError('report authorization or version changed during import')
            # If a process died after rename but before SQLite commit, accept only
            # the exact clean Git tree rebuilt from the still-authorized source.
            if target.exists() or target.is_symlink():
                if target.is_symlink() or not target.is_dir() or _tree(target) != staged_tree:
                    raise LocalReportSyncConflict('existing report workspace differs from Manager source')
            from .authoring.bundle_job_artifacts import restore_job_artifacts
            restore_job_artifacts(*imported['deferred_job_artifacts'])
            from .authoring.tree_paths import report_tree_paths
            from .local_sync_baseline import content_digest, write_baseline
            staged_digest = content_digest(staged, report_tree_paths(staged, 'main'), imported['head'])
            if not target.exists():
                os.rename(staged, target)
            target_digest = content_digest(target, report_tree_paths(target, 'main'), imported['head'])
            if staged_digest != target_digest:
                raise LocalReportSyncConflict('local report resources differ from imported source')
            operation = 'server-report-' + hashlib.sha256((manager_hash + '\0' + report_id).encode()).hexdigest()
            with store._connect() as db:
                db.execute('BEGIN IMMEDIATE')
                if source_kind == 'local':
                    parent = db.execute('SELECT profile_id FROM researches WHERE research_id=?', (research_id,)).fetchone()
                    if parent is not None and parent['profile_id'] != profile:
                        raise LocalReportSyncConflict('local Research belongs to another profile')
                    if parent is None:
                        now = time.time()
                        parent_operation = 'shared-research-' + hashlib.sha256(research_id.encode()).hexdigest()
                        db.execute('INSERT INTO researches VALUES (?, ?, ?, ?, ?, ?, ?)',
                                   (research_id, profile, owner_metadata['research_title'], '', parent_operation, now, now))
                if db.execute('SELECT 1 FROM reports WHERE report_id=? OR operation_id=?', (report_id, operation)).fetchone():
                    raise LocalReportSyncConflict('local report changed during import')
                db.execute('INSERT INTO reports VALUES (?, ?, ?, ?, ?, ?, 1)',
                           (report_id, research_id, profile, title, operation, time.time()))
                db.execute('''INSERT INTO report_publications (report_id,manager_hash,publication_id,revision,generation,
                    projection_hash,local_root_ref,source_kind) VALUES (?,?,?,?,?,?,?,?)''',
                    (report_id, manager_hash, record['publication_id'], record['revision'], record['generation'],
                     record['projection_hash'], imported['head']['root_ref'], source_kind))
                row = db.execute('SELECT * FROM reports WHERE report_id=?', (report_id,)).fetchone()
            write_baseline(store, report_id=report_id, manager_hash=manager_hash,
                receipt={**record, 'local_root_ref': imported['head']['root_ref']}, content_sha256=staged_digest)
            return {'status': 'imported', 'report': store._report_public(row)}
