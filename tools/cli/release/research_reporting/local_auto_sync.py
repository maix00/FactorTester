"""Bounded synchronization of reports explicitly published by this client."""
from __future__ import annotations

import hashlib

from tools.cli.http import HttpClientError
from .authoring.tree_paths import report_tree_paths
from .authoring.tree_store import load_head, tree_lock
from .local_publication import ensure_publication_table, manager_session, publish_local_report
from .local_pull import LocalReportSyncConflict, _remote, pull_local_report

_PUBLICATION_PAGE = '''SELECT report.report_id, report.research_id, publication.manager_hash, publication.publication_id, publication.revision,
                   publication.generation, publication.local_root_ref, publication.source_kind,
                   EXISTS(SELECT 1 FROM report_pull_recovery AS recovery
                          WHERE recovery.report_id=publication.report_id AND recovery.manager_hash=publication.manager_hash) AS pending_pull
            FROM report_publications AS publication JOIN reports AS report ON report.report_id=publication.report_id
            WHERE publication.manager_hash=? AND report.profile_id=? AND report.ready=1 AND publication.report_id>?
            ORDER BY publication.report_id LIMIT ?'''


def _restore_missing_baseline(store, *, root, paths, head, row, snapshot, session, binding, manager):
    """Rebuild an old receipt's cache only against its still-current Manager source."""
    from .local_catalog_import import verify_equivalent_authoring
    from .local_pull import _require_clean_workspace
    from .local_sync_baseline import content_digest, write_baseline

    report_id, research_id = row['report_id'], row['research_id']
    with tree_lock(paths):
        _require_clean_workspace(root)
    complete = _remote(session, research_id, report_id, source_kind=row['source_kind'])
    if (complete['publication'], complete['authoring']) != (snapshot['publication'], snapshot['authoring']):
        raise LocalReportSyncConflict('remote report changed during baseline recovery')
    local_sha = verify_equivalent_authoring(store, root=root, head=head, remote=complete, session=session,
        research_id=research_id, report_id=report_id, source_kind=row['source_kind'])
    confirmed = _remote(session, research_id, report_id, metadata_only=True, requires_edit=True,
                        source_kind=row['source_kind'])
    identity = session.get('/api/session')
    if (confirmed != snapshot or not isinstance(identity, dict)
            or str(identity.get('keycloak_issuer') or '').rstrip('/') != binding['issuer']
            or identity.get('tr_identity_id') != binding['identity_id']
            or identity.get('keycloak_subject') != manager['subject']
            or identity.get('visitor_login') is True or identity.get('role') == 'visitor'
            or identity.get('authentication') == 'agent'
            or not isinstance(identity.get('username'), str) or not identity['username'].strip()):
        raise PermissionError('report authorization or identity changed during baseline recovery')
    with tree_lock(paths):
        current = load_head(paths)
        if (current['generation'], current['root_ref']) != (head['generation'], head['root_ref']):
            raise LocalReportSyncConflict('local report changed during baseline recovery')
        _require_clean_workspace(root)
        if content_digest(root, paths, current) != local_sha:
            raise LocalReportSyncConflict('local report resources changed during baseline recovery')
        with store._connect() as db:
            receipt = db.execute('SELECT * FROM report_publications WHERE report_id=? AND manager_hash=?',
                                 (report_id, row['manager_hash'])).fetchone()
        if (not receipt or any(receipt[key] != row[key] for key in
                ('publication_id', 'revision', 'generation', 'local_root_ref', 'source_kind'))):
            raise LocalReportSyncConflict('report receipt changed during baseline recovery')
        write_baseline(store, report_id=report_id, manager_hash=row['manager_hash'],
                       receipt=receipt, content_sha256=local_sha)


def sync_published_reports(store, *, binding: dict, manager: dict, profile_id: str,
                           after_report_id: str, limit: int) -> dict:
    profile = store._profile(profile_id)
    if type(limit) is not int or not 1 <= limit <= 16 or not isinstance(after_report_id, str) or len(after_report_id) > 160:
        raise ValueError('invalid report synchronization page')
    endpoint, session = manager_session(binding, manager)
    manager_hash = hashlib.sha256(endpoint.encode()).hexdigest()
    ensure_publication_table(store)
    with store._connect() as db:
        rows = db.execute(_PUBLICATION_PAGE, (manager_hash, profile, after_report_id, limit + 1)).fetchall()
    results = []
    for row in rows[:limit]:
        report_id, research_id = row['report_id'], row['research_id']
        try:
            _item, root = store._report_root(profile, research_id, report_id)
            paths = report_tree_paths(root, 'main')
            with tree_lock(paths):
                head = load_head(paths)
            snapshot = _remote(session, research_id, report_id, metadata_only=True, source_kind=row['source_kind'])
            remote, authoring = snapshot['publication'], snapshot['authoring']
            if remote['publication_id'] != row['publication_id']:
                raise LocalReportSyncConflict('remote publication identity changed')
            local_changed = not row['local_root_ref'] or (head['generation'], head['root_ref']) != (row['generation'], row['local_root_ref'])
            remote_changed = remote['revision'] != row['revision']
            if local_changed and remote_changed and row['pending_pull']:
                # Let the pull verify the recorded source, base receipt and Git
                # commit before treating an interrupted pull as a conflict.
                pulled = pull_local_report(store, binding=binding, manager=manager, profile_id=profile,
                                           research_id=research_id, report_id=report_id)
                status = 'updated' if pulled['status'] == 'updated' else 'unchanged'
            elif local_changed and remote_changed:
                same_root = (head['generation'], head['root_ref']) == (authoring['generation'], authoring['root_ref'])
                same_projection = False
                local_projection = None
                if same_root:
                    # The server validates each projection and authoring tree
                    # separately. Their root alone does not prove that both
                    # representations describe the same report.
                    from .authoring.tree_projection import project_snapshot
                    from .public_research.object_uploads import detach_object_bytes, projection_hash
                    from .public_research.projection import build_upload_projection
                    with tree_lock(paths):
                        current = load_head(paths)
                        if (current['generation'], current['root_ref']) == (head['generation'], head['root_ref']):
                            local_projection, _uploads = detach_object_bytes(build_upload_projection(project_snapshot(paths, current)))
                            same_projection = local_projection['projection_hash'] == remote['projection_hash']
                    if not same_projection and local_projection is not None:
                        # HEAD mtime is not part of the immutable report tree;
                        # it can change after copying or a recovered pull. Check
                        # the source-free projection with that one field aligned.
                        complete = _remote(session, research_id, report_id, source_kind=row['source_kind'])
                        projected = complete.get('projection')
                        if (complete.get('publication') == remote and complete.get('authoring') == authoring
                                and isinstance(projected, dict) and 'updated_at' in projected):
                            local_projection['updated_at'] = projected['updated_at']
                            same_projection = projection_hash(local_projection) == remote['projection_hash']
                if not same_root or not same_projection:
                    status = 'conflict'
                else:
                    # A root and the published projection do not cover every
                    # editable attachment or private link in the authoring
                    # bundle. Validate that content before advancing a receipt.
                    from .authoring.tree_bundle import bundle_from_snapshot, bundle_content_digest
                    from .authoring.tree_projection import project_snapshot
                    from .local_catalog_import import verify_equivalent_authoring
                    identity = session.get('/api/session')
                    complete = _remote(session, research_id, report_id, source_kind=row['source_kind'])
                    if (complete['publication'], complete['authoring']) != (remote, authoring):
                        raise LocalReportSyncConflict('remote report changed during comparison')
                    local_sha = verify_equivalent_authoring(store, root=root, head=head, remote=complete,
                        session=session, research_id=research_id, report_id=report_id, source_kind=row['source_kind'])
                    confirmed = _remote(session, research_id, report_id, metadata_only=True,
                                        requires_edit=True, source_kind=row['source_kind'])
                    current_identity = session.get('/api/session')
                    if (confirmed != snapshot or not isinstance(identity, dict) or not isinstance(current_identity, dict)
                            or str(identity.get('keycloak_issuer') or '').rstrip('/') != binding['issuer']
                            or identity.get('tr_identity_id') != binding['identity_id']
                            or identity.get('keycloak_subject') != manager['subject']
                            or identity.get('visitor_login') is True or identity.get('role') == 'visitor'
                            or identity.get('authentication') == 'agent'
                            or not isinstance(identity.get('username'), str) or not identity['username'].strip()
                            or any(current_identity.get(key) != identity.get(key) for key in
                                   ('username', 'keycloak_issuer', 'keycloak_subject', 'tr_identity_id',
                                    'visitor_login', 'role', 'authentication'))):
                        raise PermissionError('report authorization or identity changed during comparison')
                    with tree_lock(paths):
                        current = load_head(paths)
                        if (current['generation'], current['root_ref']) != (head['generation'], head['root_ref']):
                            raise LocalReportSyncConflict('local report changed during comparison')
                        data = bundle_from_snapshot(project_snapshot(paths, current), package_root=root, branch_id='main')
                        if bundle_content_digest(data) != local_sha:
                            raise LocalReportSyncConflict('local report resources changed during comparison')
                        with store._connect() as db:
                            result = db.execute('''UPDATE report_publications
                                SET revision=?, generation=?, projection_hash=?, local_root_ref=?
                                WHERE report_id=? AND manager_hash=? AND publication_id=? AND revision=?
                                  AND generation=? AND local_root_ref=?''',
                                (remote['revision'], head['generation'], remote['projection_hash'], head['root_ref'],
                                 report_id, manager_hash, row['publication_id'], row['revision'],
                                 row['generation'], row['local_root_ref']))
                        if result.rowcount == 1:
                            from .local_sync_baseline import write_baseline
                            write_baseline(store, report_id=report_id, manager_hash=manager_hash,
                                receipt={**remote, 'local_root_ref': head['root_ref']}, content_sha256=local_sha)
                        status = 'unchanged' if result.rowcount == 1 else 'conflict'
            elif local_changed:
                publish_local_report(store, binding=binding, manager=manager, profile_id=profile,
                                     research_id=research_id, report_id=report_id)
                status = 'published'
            elif remote_changed:
                pulled = pull_local_report(store, binding=binding, manager=manager, profile_id=profile,
                                           research_id=research_id, report_id=report_id)
                status = 'updated' if pulled['status'] == 'updated' else 'unchanged'
            else:
                from .local_sync_baseline import content_check_due, content_digest, mark_content_checked, read_baseline
                baseline = read_baseline(store, report_id=report_id, manager_hash=manager_hash, receipt=row)
                if baseline is None:
                    _restore_missing_baseline(store, root=root, paths=paths, head=head, row=row,
                        snapshot=snapshot, session=session, binding=binding, manager=manager)
                    status = 'unchanged'
                elif content_check_due(store, report_id=report_id, manager_hash=manager_hash):
                    with tree_lock(paths):
                        current = load_head(paths)
                        if (current['generation'], current['root_ref']) != (head['generation'], head['root_ref']):
                            raise LocalReportSyncConflict('local report changed during content check')
                        try:
                            current_digest = content_digest(root, paths, current)
                        except (OSError, ValueError) as exc:
                            # Hashed report assets reject changed bytes during
                            # bundling. Preserve the edit and report a conflict;
                            # unrelated missing dependencies remain unavailable.
                            from .local_pull import _assets_changed
                            if _assets_changed(root, paths, current):
                                raise LocalReportSyncConflict('local report asset changed') from exc
                            raise
                    if current_digest != baseline:
                        # The server requires a new report generation for a
                        # different authoring bundle. Until that version is
                        # explicitly produced, preserve the local bytes and
                        # surface a conflict instead of silently losing them.
                        status = 'conflict'
                    else:
                        mark_content_checked(store, report_id=report_id, manager_hash=manager_hash,
                                             receipt=row, content_sha256=baseline)
                        status = 'unchanged'
                else:
                    status = 'unchanged'
        except LocalReportSyncConflict:
            status = 'conflict'
        except HttpClientError as exc:
            status = 'conflict' if exc.status == 409 else 'denied' if exc.status in {401, 403} else 'unavailable'
        except PermissionError:
            status = 'denied'
        except (OSError, RuntimeError, ValueError):
            status = 'unavailable'
        results.append({'research_id': research_id, 'report_id': report_id, 'status': status})
    from .local_server_research import retry_pending_server_research
    researches, pending_more = retry_pending_server_research(store, binding=binding, manager=manager,
                                                             profile_id=profile, limit=limit)
    from .local_server_reports import sync_server_reports
    from .local_shared_discovery import discover_local_reports
    try:
        local_more, local_scan_errors = discover_local_reports(store, session=session, manager_hash=manager_hash,
                                                               profile_id=profile, limit=limit)
    except ValueError:
        local_more, local_scan_errors = False, [{'research_id': '', 'status': 'unavailable'}]
    imports, imports_more, scan_errors = sync_server_reports(store, binding=binding, manager=manager, profile_id=profile,
                                                limit=limit, endpoint=endpoint, session=session)
    return {'reports': results, 'researches': researches, 'report_imports': imports,
            'researches_pending_more': pending_more, 'report_imports_pending_more': imports_more or local_more,
            'report_scans': scan_errors + local_scan_errors,
            'next_report_id': rows[limit - 1]['report_id'] if len(rows) > limit else None}
