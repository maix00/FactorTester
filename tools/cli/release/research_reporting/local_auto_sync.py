"""Bounded synchronization of reports explicitly published by this client."""
from __future__ import annotations

import hashlib

from tools.cli.http import HttpClientError
from .authoring.tree_paths import report_tree_paths
from .authoring.tree_store import load_head, tree_lock
from .local_publication import ensure_publication_table, manager_session, publish_local_report
from .local_pull import LocalReportSyncConflict, _remote, pull_local_report

_PUBLICATION_PAGE = '''SELECT report.report_id, report.research_id, publication.revision,
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
            remote = _remote(session, research_id, report_id, metadata_only=True)['publication']
            local_changed = not row['local_root_ref'] or (head['generation'], head['root_ref']) != (row['generation'], row['local_root_ref'])
            remote_changed = remote['revision'] != row['revision']
            if local_changed and remote_changed:
                status = 'conflict'
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
    return {'reports': results, 'next_report_id': rows[limit - 1]['report_id'] if len(rows) > limit else None}
