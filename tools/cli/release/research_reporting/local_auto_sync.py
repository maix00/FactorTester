"""Bounded synchronization of reports explicitly published by this client."""
from __future__ import annotations

import hashlib

from tools.cli.http import HttpClientError
from .authoring.tree_paths import report_tree_paths
from .authoring.tree_store import load_head, tree_lock
from .local_publication import ensure_publication_table, manager_session, publish_local_report
from .local_pull import LocalReportSyncConflict, _remote, pull_local_report

_PUBLICATION_PAGE = '''SELECT report.report_id, report.research_id, publication.publication_id, publication.revision,
                   publication.generation, publication.local_root_ref
            FROM report_publications AS publication JOIN reports AS report ON report.report_id=publication.report_id
            WHERE publication.manager_hash=? AND report.profile_id=? AND report.ready=1 AND publication.report_id>?
            ORDER BY publication.report_id LIMIT ?'''


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
            snapshot = _remote(session, research_id, report_id, metadata_only=True)
            remote, authoring = snapshot['publication'], snapshot['authoring']
            if remote['publication_id'] != row['publication_id']:
                raise LocalReportSyncConflict('remote publication identity changed')
            local_changed = not row['local_root_ref'] or (head['generation'], head['root_ref']) != (row['generation'], row['local_root_ref'])
            remote_changed = remote['revision'] != row['revision']
            if local_changed and remote_changed:
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
                        complete = _remote(session, research_id, report_id)
                        projected = complete.get('projection')
                        if (complete.get('publication') == remote and complete.get('authoring') == authoring
                                and isinstance(projected, dict) and 'updated_at' in projected):
                            local_projection['updated_at'] = projected['updated_at']
                            same_projection = projection_hash(local_projection) == remote['projection_hash']
                if not same_root or not same_projection:
                    status = 'conflict'
                else:
                    # A publish/pull may commit its report before the local receipt
                    # is saved. Identical immutable roots prove convergence; advance
                    # the receipt without writing either report again. A concurrent
                    # synchronizer must not have its newer receipt overwritten.
                    with store._connect() as db:
                        result = db.execute('''UPDATE report_publications
                            SET revision=?, generation=?, projection_hash=?, local_root_ref=?
                            WHERE report_id=? AND manager_hash=? AND publication_id=? AND revision=?
                              AND generation=? AND local_root_ref=?''',
                            (remote['revision'], head['generation'], remote['projection_hash'], head['root_ref'],
                             report_id, manager_hash, row['publication_id'], row['revision'],
                             row['generation'], row['local_root_ref']))
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
    return {'reports': results, 'researches': researches,
            'researches_pending_more': pending_more,
            'next_report_id': rows[limit - 1]['report_id'] if len(rows) > limit else None}
