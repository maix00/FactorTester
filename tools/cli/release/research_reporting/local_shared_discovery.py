"""Bounded discovery of this user's explicitly shared local report branches."""
from __future__ import annotations

from tools.cli.http import HttpClientError
from .report_workspace_identity import report_workspace_id_for
from .research_identity import is_research_ref


def discover_local_reports(store, *, session, manager_hash: str, profile_id: str, limit: int):
    """Queue identities only; source bytes and authorization are checked on import."""
    profile = store._profile(profile_id)
    with store._connect() as db:
        db.execute('INSERT OR IGNORE INTO local_report_discovery (manager_hash, profile_id) VALUES (?, ?)',
                   (manager_hash, profile))
        cursor = db.execute('SELECT cursor FROM local_report_discovery WHERE manager_hash=? AND profile_id=?',
                            (manager_hash, profile)).fetchone()['cursor']
    try:
        value = session.get('/api/research/owned-local-report-sync', query={'cursor': cursor, 'limit': limit})
    except HttpClientError as exc:
        if exc.status == 400 and cursor:
            with store._connect() as db:
                db.execute('UPDATE local_report_discovery SET cursor=? WHERE manager_hash=? AND profile_id=? AND cursor=?',
                           ('', manager_hash, profile, cursor))
            return True, []
        return False, [{'research_id': '', 'status': 'denied' if exc.status in {401, 403} else 'unavailable'}]
    except (OSError, RuntimeError):
        return False, [{'research_id': '', 'status': 'unavailable'}]
    rows, next_cursor = (value.get('reports'), value.get('next_cursor')) if isinstance(value, dict) else (None, None)
    if (not isinstance(value, dict) or value.get('success') is not True or not isinstance(rows, list) or len(rows) > limit
            or (next_cursor is not None and (not isinstance(next_cursor, str) or not next_cursor
                or len(next_cursor) > 2048 or next_cursor == cursor))):
        raise ValueError('invalid local shared report directory page')
    seen, accepted, errors = set(), [], []
    for item in rows:
        if (not isinstance(item, dict) or set(item) != {'research_id', 'report_id', 'research_title',
                'metadata_status', 'publication', 'editable', 'authoring'}
                or not isinstance(item['research_id'], str)
                or not is_research_ref(item['research_id'])
                or not isinstance(item['report_id'], str) or item['report_id'] in seen
                or not isinstance(item['publication'], dict) or item['publication'].get('report_id') != item['report_id']
                or type(item['editable']) is not bool or item['metadata_status'] not in {'ready', 'needs_repair'}):
            raise ValueError('invalid shared report identity')
        report_workspace_id_for(item['report_id'])
        seen.add(item['report_id'])
        if item['metadata_status'] != 'ready':
            errors.append({'research_id': item['research_id'], 'status': 'conflict'})
        elif not item['editable'] or not isinstance(item['authoring'], dict):
            errors.append({'research_id': item['research_id'], 'status': 'denied'})
        elif not isinstance(item['research_title'], str) or not item['research_title'].strip() or len(item['research_title']) > 256:
            raise ValueError('invalid shared Research title')
        else:
            accepted.append((item['research_id'], item['report_id']))
    with store._connect() as db:
        db.execute('BEGIN IMMEDIATE')
        current = db.execute('SELECT cursor FROM local_report_discovery WHERE manager_hash=? AND profile_id=?',
                             (manager_hash, profile)).fetchone()
        if current is None or current['cursor'] != cursor:
            return True, []
        count = db.execute('SELECT count(*) FROM server_report_pending').fetchone()[0]
        for research_id, report_id in accepted:
            existing = db.execute('''SELECT report.research_id, report.profile_id, report.ready, publication.source_kind
                FROM reports report LEFT JOIN report_publications publication
                  ON publication.report_id=report.report_id AND publication.manager_hash=?
                WHERE report.report_id=?''', (manager_hash, report_id)).fetchone()
            if existing is not None:
                if (existing['research_id'], existing['profile_id'], existing['ready']) != (research_id, profile, 1):
                    errors.append({'research_id': research_id, 'status': 'conflict'})
                    continue
                if existing['source_kind'] == 'local':
                    continue
                if existing['source_kind'] is not None:
                    errors.append({'research_id': research_id, 'status': 'conflict'})
                    continue
                # A workspace already known from another Manager is not yet
                # trusted here. Queue it for an authorized, byte-exact check.
            pending = db.execute('''SELECT research_id,source_kind FROM server_report_pending
                WHERE report_id=? AND manager_hash=? AND profile_id=?''', (report_id, manager_hash, profile)).fetchone()
            if pending:
                if (pending['research_id'], pending['source_kind']) != (research_id, 'local'):
                    errors.append({'research_id': research_id, 'status': 'conflict'})
                continue
            if count >= 1000:
                raise ValueError('too many pending report imports')
            db.execute('''INSERT INTO server_report_pending (research_id,report_id,manager_hash,profile_id,source_kind)
                          VALUES (?,?,?,?,?)''', (research_id, report_id, manager_hash, profile, 'local'))
            count += 1
        db.execute('UPDATE local_report_discovery SET cursor=? WHERE manager_hash=? AND profile_id=? AND cursor=?',
                   (next_cursor or '', manager_hash, profile, cursor))
    return next_cursor is not None, errors
