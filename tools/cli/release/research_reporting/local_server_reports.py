"""Bounded discovery and import of editable owned Manager reports."""
from __future__ import annotations

import hashlib
import time

from tools.cli.http import HttpClientError
from .local_catalog_import import import_catalog_report
from .local_pull import LocalReportSyncConflict
from .report_workspace_identity import report_workspace_id_for


def queue_report_scans(store, *, manager_hash: str, profile_id: str, research_ids: list[str]) -> None:
    with store._connect() as db:
        db.execute('BEGIN IMMEDIATE')
        count = db.execute('SELECT count(*) FROM server_report_scans').fetchone()[0]
        for ref in research_ids:
            if db.execute('SELECT 1 FROM server_report_scans WHERE research_id=? AND manager_hash=? AND profile_id=?',
                          (ref, manager_hash, profile_id)).fetchone():
                continue
            if count >= 1000:
                raise ValueError('too many pending report scans')
            db.execute('INSERT INTO server_report_scans (research_id,manager_hash,profile_id) VALUES (?,?,?)',
                       (ref, manager_hash, profile_id))
            count += 1


def sync_server_reports(store, *, binding: dict, manager: dict, profile_id: str, limit: int, endpoint: str, session) -> tuple[list[dict], bool, list[dict]]:
    profile = store._profile(profile_id)
    manager_hash = hashlib.sha256(endpoint.encode()).hexdigest()
    with store._connect() as db:
        scan = db.execute('''SELECT scan.* FROM server_report_scans AS scan JOIN server_research_origins AS origin
            ON origin.research_id=scan.research_id AND origin.manager_hash=scan.manager_hash AND origin.profile_id=scan.profile_id
            WHERE scan.manager_hash=? AND scan.profile_id=? ORDER BY scan.last_attempt,scan.research_id LIMIT 1''',
            (manager_hash, profile)).fetchone()
    scan_errors = []
    if scan:
        ref, cursor = scan['research_id'], scan['cursor']
        try:
            value = session.get('/api/research/owned-report-sync', query={'research_id': ref, 'cursor': cursor, 'limit': limit})
            items, next_cursor = value.get('reports'), value.get('next_cursor')
            if (value.get('success') is not True or not isinstance(items, list) or len(items) > limit
                    or (next_cursor is not None and (not isinstance(next_cursor, str) or not next_cursor
                        or len(next_cursor) > 2048 or next_cursor == cursor))):
                raise ValueError('invalid Manager report discovery response')
            ids = []
            for item in items:
                if (not isinstance(item, dict) or set(item) != {'research_id', 'report_id'} or item['research_id'] != ref
                        or not isinstance(item['report_id'], str)
                        or item['report_id'] in ids):
                    raise ValueError('unsupported or invalid Manager report identity')
                report_workspace_id_for(item['report_id'])
                ids.append(item['report_id'])
            with store._connect() as db:
                db.execute('BEGIN IMMEDIATE')
                count = db.execute('SELECT count(*) FROM server_report_pending').fetchone()[0]
                for report_id in ids:
                    if db.execute('''SELECT 1 FROM reports report JOIN report_publications publication
                            ON publication.report_id=report.report_id
                            WHERE report.report_id=? AND report.research_id=? AND report.profile_id=? AND report.ready=1
                              AND publication.manager_hash=? ''',
                            (report_id, ref, profile, manager_hash)).fetchone():
                        continue
                    if db.execute('SELECT 1 FROM server_report_pending WHERE report_id=? AND manager_hash=? AND profile_id=?',
                                  (report_id, manager_hash, profile)).fetchone():
                        continue
                    if count >= 1000: raise ValueError('too many pending report imports')
                    db.execute('INSERT INTO server_report_pending (research_id,report_id,manager_hash,profile_id) VALUES (?,?,?,?)',
                               (ref, report_id, manager_hash, profile))
                    count += 1
                if next_cursor:
                    db.execute('UPDATE server_report_scans SET cursor=?,last_attempt=0 WHERE research_id=? AND manager_hash=? AND profile_id=? AND cursor=?',
                               (next_cursor, ref, manager_hash, profile, cursor))
                else:
                    db.execute('DELETE FROM server_report_scans WHERE research_id=? AND manager_hash=? AND profile_id=? AND cursor=?',
                               (ref, manager_hash, profile, cursor))
        except (HttpClientError, OSError, RuntimeError, ValueError, PermissionError) as exc:
            with store._connect() as db:
                if isinstance(exc, HttpClientError) and exc.status == 400 and cursor:
                    # Cursors expire on Manager restart. Retry once from the
                    # start; a 400 on the first page waits for the next cycle.
                    db.execute('UPDATE server_report_scans SET cursor=?,last_attempt=0 WHERE research_id=? AND manager_hash=? AND profile_id=? AND cursor=?',
                               ('', ref, manager_hash, profile, cursor))
                else:
                    status = 'denied' if isinstance(exc, PermissionError) or (isinstance(exc, HttpClientError) and exc.status in {401, 403}) else 'unavailable'
                    scan_errors.append({'research_id': ref, 'status': status})
                    db.execute('UPDATE server_report_scans SET last_attempt=? WHERE research_id=? AND manager_hash=? AND profile_id=?',
                               (time.time(), ref, manager_hash, profile))
    with store._connect() as db:
        pending = db.execute('''SELECT * FROM server_report_pending WHERE manager_hash=? AND profile_id=?
            ORDER BY last_attempt,report_id LIMIT ?''', (manager_hash, profile, limit)).fetchall()
    results = []
    for row in pending:
        try:
            result = import_catalog_report(store, binding=binding, manager=manager, profile_id=profile,
                                           research_id=row['research_id'], report_id=row['report_id'])
            status = result['status']
            with store._connect() as db:
                db.execute('DELETE FROM server_report_pending WHERE report_id=? AND manager_hash=? AND profile_id=?',
                           (row['report_id'], manager_hash, profile))
        except HttpClientError as exc:
            status = 'denied' if exc.status in {401, 403} else 'unavailable'
        except PermissionError:
            status = 'denied'
        except LocalReportSyncConflict:
            status = 'conflict'
        except (OSError, RuntimeError, ValueError):
            status = 'unavailable'
        if status in {'denied', 'conflict', 'unavailable'}:
            with store._connect() as db:
                db.execute('UPDATE server_report_pending SET last_attempt=? WHERE report_id=? AND manager_hash=? AND profile_id=?',
                           (time.time(), row['report_id'], manager_hash, profile))
        results.append({'research_id': row['research_id'], 'report_id': row['report_id'], 'status': status})
    with store._connect() as db:
        more = db.execute('''SELECT 1 FROM server_report_pending WHERE manager_hash=? AND profile_id=? AND last_attempt=0
            UNION ALL SELECT 1 FROM server_report_scans scan JOIN server_research_origins origin
              ON origin.research_id=scan.research_id AND origin.manager_hash=scan.manager_hash AND origin.profile_id=scan.profile_id
              WHERE scan.manager_hash=? AND scan.profile_id=? AND scan.last_attempt=0 LIMIT 1''',
            (manager_hash, profile, manager_hash, profile)).fetchone() is not None
    return results, more, scan_errors
