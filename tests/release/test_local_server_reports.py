"""Bounded report discovery retries expired cursors and surfaces bad pages."""
import hashlib

from tools.cli.http import HttpClientError
from tools.cli.release.research_reporting.local_catalog import LocalResearchCatalog
from tools.cli.release.research_reporting.local_publication import ensure_publication_table
from tools.cli.release.research_reporting.local_server_reports import queue_report_scans, sync_server_reports


def test_scan_expired_cursor_restarts_once_and_rejects_unusable_page(tmp_path):
    endpoint = 'https://manager.test'
    manager_hash = hashlib.sha256(endpoint.encode()).hexdigest()
    store = LocalResearchCatalog(tmp_path, issuer='https://issuer.test/realm', identity_id='stable', profiles={'self'})
    ensure_publication_table(store)
    with store._connect() as db:
        db.execute('INSERT INTO researches VALUES (?,?,?,?,?,?,?)', ('research', 'self', 'Research', '', 'operation', 1, 1))
        db.execute('INSERT INTO server_research_origins VALUES (?,?,?,?,?,?)', ('research', manager_hash, 'self', 'Research', '', 1))
    queue_report_scans(store, manager_hash=manager_hash, profile_id='self', research_ids=['research'])
    with store._connect() as db:
        db.execute("UPDATE server_report_scans SET cursor='expired'")
    class Session:
        def __init__(self): self.calls = []
        def get(self, _path, *, query):
            self.calls.append(query['cursor'])
            if query['cursor']: raise HttpClientError(400, endpoint, 'expired')
            return {'success': True, 'reports': [{'research_id': 'research', 'report_id': '../invalid'}], 'next_cursor': None}
    session = Session()
    kwargs = dict(binding={}, manager={}, profile_id='self', limit=2, endpoint=endpoint, session=session)
    results, more, errors = sync_server_reports(store, **kwargs)
    assert results == [] and more is True and errors == []
    results, more, errors = sync_server_reports(store, **kwargs)
    assert results == [] and more is False and errors == [{'research_id': 'research', 'status': 'unavailable'}]
    assert session.calls == ['expired', '']
    with store._connect() as db:
        assert db.execute('SELECT count(*) FROM server_report_pending').fetchone()[0] == 0
        assert db.execute('SELECT last_attempt FROM server_report_scans').fetchone()[0] > 0


def test_existing_local_publication_is_not_reimported_as_catalog_report(tmp_path):
    endpoint = 'https://manager.test'
    manager_hash = hashlib.sha256(endpoint.encode()).hexdigest()
    store = LocalResearchCatalog(tmp_path, issuer='https://issuer.test/realm', identity_id='stable', profiles={'self'})
    ensure_publication_table(store)
    with store._connect() as db:
        db.execute('INSERT INTO researches VALUES (?,?,?,?,?,?,?)', ('research', 'self', 'Research', '', 'operation', 1, 1))
        db.execute('INSERT INTO server_research_origins VALUES (?,?,?,?,?,?)', ('research', manager_hash, 'self', 'Research', '', 1))
        db.execute('INSERT INTO reports VALUES (?,?,?,?,?,?,?)', ('report-1', 'research', 'self', 'Report', 'report-op', 1, 1))
        db.execute('''INSERT INTO report_publications (report_id,manager_hash,publication_id,revision,generation,projection_hash,local_root_ref)
            VALUES (?,?,?,?,?,?,?)''', ('report-1', manager_hash, 'p', 'rev', 1, 'hash', 'root'))
    queue_report_scans(store, manager_hash=manager_hash, profile_id='self', research_ids=['research'])
    class Session:
        def get(self, _path, *, query):
            return {'success': True, 'reports': [{'research_id': 'research', 'report_id': 'report-1'}], 'next_cursor': None}
    results, more, errors = sync_server_reports(store, binding={}, manager={}, profile_id='self', limit=2,
                                                 endpoint=endpoint, session=Session())
    assert results == [] and more is False and errors == []
    with store._connect() as db:
        assert db.execute('SELECT count(*) FROM server_report_pending').fetchone()[0] == 0
