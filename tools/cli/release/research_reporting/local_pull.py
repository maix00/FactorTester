"""Fetch one authorized report branch without overwriting local edits."""
from __future__ import annotations

import hashlib
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlencode

from .authoring.tree_bundle import import_report_bundle
from .authoring.tree_paths import report_tree_paths
from .authoring.tree_sqlite_index import publish_sqlite_index
from .authoring.tree_store import atomic_write, load_head, load_node, tree_lock, write_head
from .authoring.submission_status import require_no_pending
from .generation import report_workspace_lock
from .git import commit_report_workspace
from .local_publication import ensure_publication_table, manager_session
from .report_workspace_identity import report_workspace_id_for


class LocalReportSyncConflict(ValueError):
    """Local and remote report histories cannot safely be advanced automatically."""


def _remote(session, research_id: str, report_id: str, *, metadata_only: bool = False, requires_edit: bool = False) -> dict:
    from .public_research.object_uploads import projection_hash
    value = session.get('/api/research/local-report-publication', query={
        'research_id': research_id, 'report_id': report_id, 'branch_ref': 'main',
        **({'metadata_only': '1'} if metadata_only else {}),
        **({'requires_edit': '1'} if requires_edit else {})})
    record, bundle, projection = value.get('publication'), value.get('authoring'), value.get('projection')
    if (value.get('success') is not True or (requires_edit and value.get('edit_authorized') is not True)
            or not isinstance(record, dict) or not isinstance(bundle, dict) or (not metadata_only and not isinstance(projection, dict))
            or record.get('report_id') != report_id or record.get('branch_ref') != 'main'
            or not re.fullmatch(r'p-[0-9a-f]{64}', str(record.get('publication_id') or ''))
            or not isinstance(record.get('revision'), str) or not record['revision'] or len(record['revision']) > 256
            or type(record.get('generation')) is not int or record['generation'] < 0
            or not re.fullmatch(r'[0-9a-f]{64}', str(record.get('projection_hash') or ''))
            or (not metadata_only and (projection.get('report_id') != report_id or projection.get('generation') != record['generation']
                or projection.get('projection_hash') != record['projection_hash'] or projection_hash(projection) != record['projection_hash']))
            or set(bundle) != {'sha256', 'root_ref', 'generation', 'size_bytes'}
            or not re.fullmatch(r'[0-9a-f]{64}', str(bundle.get('sha256') or ''))
            or bundle.get('generation') != record['generation']
            or type(bundle.get('size_bytes')) is not int or not 0 < bundle['size_bytes'] <= 8 * 1024 * 1024):
        raise ValueError('remote report snapshot is invalid or not editable')
    from .authoring.tree_schema import node_reference
    node_reference(bundle['root_ref'])
    return {'publication': record, 'authoring': bundle,
            **({'projection': projection} if not metadata_only else {})}


def _copy_files(source: Path, destination: Path, created: list[Path]) -> None:
    if not source.exists():
        return
    for path in source.rglob('*'):
        if path.is_symlink():
            raise ValueError('report snapshot contains a symbolic link')
        if not path.is_file():
            continue
        target = destination / path.relative_to(source)
        for parent in [target, *target.parents]:
            if parent.is_symlink():
                raise ValueError('report destination contains a symbolic link')
            if parent == destination.parent:
                break
        data = path.read_bytes()
        if target.exists():
            if not target.is_file() or target.read_bytes() != data:
                raise LocalReportSyncConflict('local report resource differs from remote content')
        else:
            created.append(target)
            atomic_write(target, data)


def _recover_pull(store, root: Path, paths: dict, manager_hash: str, report_id: str,
                  remote: dict, base, local: dict) -> bool:
    """Finish a verified pull whose Git commit preceded its SQLite receipt."""
    with store._connect() as db:
        pending = db.execute('SELECT * FROM report_pull_recovery WHERE report_id=? AND manager_hash=?',
                             (report_id, manager_hash)).fetchone()
    if not pending:
        return False
    record, bundle = remote['publication'], remote['authoring']
    if (not base or (base['publication_id'], base['revision'], base['generation'], base['local_root_ref']) !=
            (pending['publication_id'], pending['base_revision'], pending['base_generation'], pending['base_root_ref'])
            or (record['publication_id'], record['revision'], record['generation'], record['projection_hash'], bundle['sha256']) !=
            (pending['publication_id'], pending['revision'], pending['generation'], pending['projection_hash'], pending['bundle_sha256'])
            or (local['generation'], local['root_ref']) != (pending['generation'], pending['local_root_ref'])):
        return False
    status = subprocess.run(['git', '-C', str(root), 'status', '--porcelain'], capture_output=True, text=True, check=True)
    parent = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD^'], capture_output=True, text=True)
    message = subprocess.run(['git', '-C', str(root), 'log', '-1', '--format=%s'], capture_output=True, text=True, check=True)
    if status.stdout.strip() or parent.returncode or parent.stdout.strip() != pending['prior_commit'] or message.stdout.strip() != 'Sync report from Manager':
        return False
    with store._connect() as db:
        changed = db.execute('''UPDATE report_publications SET revision=?, generation=?, projection_hash=?, local_root_ref=?
            WHERE report_id=? AND manager_hash=? AND publication_id=? AND revision=? AND generation=? AND local_root_ref=?''',
            (pending['revision'], pending['generation'], pending['projection_hash'], pending['local_root_ref'], report_id,
             manager_hash, pending['publication_id'], pending['base_revision'], pending['base_generation'], pending['base_root_ref']))
        if changed.rowcount != 1:
            raise LocalReportSyncConflict('report synchronization receipt changed during recovery')
        db.execute('DELETE FROM report_pull_recovery WHERE report_id=? AND manager_hash=?', (report_id, manager_hash))
    return True


def pull_local_report(store, *, binding: dict, manager: dict, profile_id: str,
                      research_id: str, report_id: str) -> dict:
    endpoint, session = manager_session(binding, manager)
    _report, root = store._report_root(profile_id, research_id, report_id)
    manager_hash = hashlib.sha256(endpoint.encode()).hexdigest()
    lock = store.workspace_root / '.locks' / ('publication-' + report_workspace_id_for(report_id) + '-' + manager_hash[:16])
    ensure_publication_table(store)
    with report_workspace_lock(lock):
        remote = _remote(session, research_id, report_id)
        record, bundle = remote['publication'], remote['authoring']
        with store._connect() as db:
            base = db.execute('SELECT * FROM report_publications WHERE report_id=? AND manager_hash=?',
                              (report_id, manager_hash)).fetchone()
        if base and base['publication_id'] != record['publication_id']:
            raise LocalReportSyncConflict('remote publication identity changed')
        paths = report_tree_paths(root, 'main')
        with tree_lock(paths):
            local = load_head(paths)
            if local['report_id'] != report_id:
                raise ValueError('local report identity is invalid')
            # Recovery updates a local editable snapshot, so recheck write access
            # just as the authoring attachment endpoint does.
            with store._connect() as db:
                has_recovery = db.execute('SELECT 1 FROM report_pull_recovery WHERE report_id=? AND manager_hash=?',
                                          (report_id, manager_hash)).fetchone() is not None
            if has_recovery:
                edit_check = _remote(session, research_id, report_id, metadata_only=True, requires_edit=True)
                if edit_check != {'publication': remote['publication'], 'authoring': remote['authoring']}:
                    raise LocalReportSyncConflict('remote report changed during recovery')
            if has_recovery and _recover_pull(store, root, paths, manager_hash, report_id, remote, base, local):
                return {'status': 'updated', 'local_modified': False}
            if base and base['revision'] == record['revision']:
                return {'status': 'up_to_date', 'local_modified': (local['generation'] != base['generation'] or local['root_ref'] != base['local_root_ref'])}
            baseline_ok = bool(base and base['local_root_ref'] and local['generation'] == base['generation'] and local['root_ref'] == base['local_root_ref'])
            identical = local['generation'] == bundle['generation'] and local['root_ref'] == bundle['root_ref']
            if not baseline_ok and not identical:
                raise LocalReportSyncConflict('local report changed since the last confirmed synchronization')
            require_no_pending(paths, local)
            expected = (local['generation'], local['root_ref'])
        publication_id, digest = record['publication_id'], bundle['sha256']
        query = urlencode({'research_id': research_id, 'report_id': report_id})
        response = session.download(f'/api/research/local-report-publication/{publication_id}/attachments/report_authoring/{digest}?{query}',
                                    maximum_bytes=8 * 1024 * 1024)
        if len(response.content) != bundle['size_bytes'] or hashlib.sha256(response.content).hexdigest() != digest:
            raise ValueError('remote report bundle checksum or size mismatch')
        with tempfile.TemporaryDirectory(prefix='report-pull-', dir=store.workspace_root) as temporary:
            staged_root = Path(temporary) / report_workspace_id_for(report_id)
            imported = import_report_bundle(payload=response.content, expected_sha256=digest, package_root=staged_root,
                branch_id='main', report_id=report_id, source_generation=bundle['generation'], source_root_ref=bundle['root_ref'])
            staged_head = imported['head']
            if _remote(session, research_id, report_id) != remote:
                raise LocalReportSyncConflict('remote report changed during download')
            target_lock = store.workspace_root / '.locks' / report_workspace_id_for(report_id)
            with report_workspace_lock(target_lock), tree_lock(paths):
                current = load_head(paths)
                if (current['generation'], current['root_ref']) != expected:
                    raise LocalReportSyncConflict('local report changed during download')
                require_no_pending(paths, current)
                status = subprocess.run(['git', '-C', str(root), 'status', '--porcelain'], capture_output=True, text=True, check=True)
                if status.stdout.strip():
                    raise LocalReportSyncConflict('local report workspace has uncommitted files')
                prior_commit = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
                registry_before = paths['binding_registry'].read_bytes() if paths['binding_registry'].exists() else None
                staged_branch = staged_root / 'branches' / 'main'
                target_branch = root / 'branches' / 'main'
                created: list[Path] = []
                head_started = False
                try:
                    if base:
                        with store._connect() as db:
                            db.execute('''INSERT OR REPLACE INTO report_pull_recovery VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                                (report_id, manager_hash, record['publication_id'], record['revision'], staged_head['generation'],
                                 record['projection_hash'], digest, staged_head['root_ref'], base['revision'], base['generation'],
                                 base['local_root_ref'], prior_commit))
                    for name in ('resources', 'assets'):
                        _copy_files(staged_branch / name, target_branch / name, created)
                    _copy_files(staged_branch / 'authoring' / 'nodes', target_branch / 'authoring' / 'nodes', created)
                    new_head = {**staged_head, 'locator_generation': 0}
                    head_started = True
                    write_head(paths, new_head)
                    try:
                        publish_sqlite_index(paths, load_node(paths, new_head['root_ref']), new_head['generation'])
                        write_head(paths, {**new_head, 'locator_generation': new_head['generation']})
                    except (OSError, ValueError):
                        # HEAD remains authoritative; indexes are rebuildable.
                        pass
                    commit_report_workspace(root, message='Sync report from Manager')
                except Exception:
                    after = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
                    if after == prior_commit:
                        staged = subprocess.check_output(['git', '-C', str(root), 'diff', '--cached', '--name-only', '-z']).decode().split('\x00')
                        allowed = {str(path.relative_to(root)) for path in created}
                        allowed.update(str(path.relative_to(root)) for path in (paths['head'], paths['binding_registry']))
                        allowed.add('.gitignore')
                        changed = [path for path in staged if path]
                        if not set(changed).issubset(allowed):
                            raise LocalReportSyncConflict('unrelated staged files appeared during report recovery')
                        if changed:
                            subprocess.run(['git', '-C', str(root), 'restore', '--staged', '--', *changed], check=True, capture_output=True)
                        if head_started:
                            write_head(paths, current)
                            if registry_before is None:
                                paths['binding_registry'].unlink(missing_ok=True)
                            else:
                                atomic_write(paths['binding_registry'], registry_before)
                            publish_sqlite_index(paths, load_node(paths, current['root_ref']), current['generation'])
                        for path in reversed(created):
                            path.unlink(missing_ok=True)
                        with store._connect() as db:
                            db.execute('DELETE FROM report_pull_recovery WHERE report_id=? AND manager_hash=?', (report_id, manager_hash))
                    raise
        with store._connect() as db:
            if base:
                changed = db.execute('''UPDATE report_publications SET revision=?, generation=?, projection_hash=?, local_root_ref=?
                    WHERE report_id=? AND manager_hash=? AND publication_id=? AND revision=? AND generation=? AND local_root_ref=?''',
                    (record['revision'], staged_head['generation'], record['projection_hash'], staged_head['root_ref'],
                     report_id, manager_hash, base['publication_id'], base['revision'], base['generation'], base['local_root_ref']))
                if changed.rowcount != 1:
                    raise LocalReportSyncConflict('report synchronization receipt changed during pull')
            else:
                db.execute('''INSERT INTO report_publications
                (report_id, manager_hash, publication_id, revision, generation, projection_hash, local_root_ref)
                VALUES (?, ?, ?, ?, ?, ?, ?)''', (report_id, manager_hash, record['publication_id'],
                    record['revision'], staged_head['generation'], record['projection_hash'], staged_head['root_ref']))
            db.execute('DELETE FROM report_pull_recovery WHERE report_id=? AND manager_hash=?', (report_id, manager_hash))
        return {'status': 'updated', 'local_modified': False}
