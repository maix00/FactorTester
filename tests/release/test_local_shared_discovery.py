from tools.cli.http import HttpClientError
from tools.cli.release.research_reporting.local_catalog import LocalResearchCatalog
from tools.cli.release.research_reporting.local_publication import ensure_publication_table
from tools.cli.release.research_reporting.local_shared_discovery import discover_local_reports


def _item(letter):
    research, report = 'research:v1:' + letter * 24, 'report:v1:' + letter * 24
    return {'research_id': research, 'report_id': report, 'research_title': 'Research', 'metadata_status': 'ready',
            'publication': {'report_id': report}, 'editable': True, 'authoring': {'sha256': 'fixture'}}


def test_discovery_queues_each_page_once_and_preserves_origin(tmp_path):
    store = LocalResearchCatalog(tmp_path, issuer='https://issuer.test/realm', identity_id='stable', profiles={'self'})
    ensure_publication_table(store)
    class Session:
        def get(self, path, *, query):
            assert path == '/api/research/owned-local-report-sync'
            return {'success': True, 'reports': [_item('A') if not query['cursor'] else _item('B')],
                    'next_cursor': 'opaque' if not query['cursor'] else None}
    kwargs = dict(session=Session(), manager_hash='manager', profile_id='self', limit=1)
    assert discover_local_reports(store, **kwargs) == (True, [])
    assert discover_local_reports(store, **kwargs) == (False, [])
    assert discover_local_reports(store, **kwargs) == (True, [])
    with store._connect() as db:
        rows = db.execute('SELECT report_id, source_kind FROM server_report_pending ORDER BY report_id').fetchall()
    assert [(row['report_id'], row['source_kind']) for row in rows] == [
        (_item('A')['report_id'], 'local'), (_item('B')['report_id'], 'local')]


def test_expired_cursor_restarts_without_discarding_pending_reports(tmp_path):
    store = LocalResearchCatalog(tmp_path, issuer='https://issuer.test/realm', identity_id='stable', profiles={'self'})
    ensure_publication_table(store)
    with store._connect() as db:
        db.execute("INSERT INTO local_report_discovery VALUES ('manager','self','expired')")
    class Session:
        def get(self, _path, *, query):
            if query['cursor']:
                raise HttpClientError(400, 'https://manager.test', 'expired')
            return {'success': True, 'reports': [_item('A')], 'next_cursor': None}
    kwargs = dict(session=Session(), manager_hash='manager', profile_id='self', limit=1)
    assert discover_local_reports(store, **kwargs) == (True, [])
    assert discover_local_reports(store, **kwargs) == (False, [])
    with store._connect() as db:
        assert db.execute('SELECT source_kind FROM server_report_pending').fetchone()['source_kind'] == 'local'


def test_existing_local_report_from_another_manager_is_queued_for_exact_validation(tmp_path):
    store = LocalResearchCatalog(tmp_path, issuer='https://issuer.test/realm', identity_id='stable', profiles={'self'})
    ensure_publication_table(store)
    item = _item('A')
    with store._connect() as db:
        db.execute('INSERT INTO researches VALUES (?,?,?,?,?,?,?)',
                   (item['research_id'], 'self', 'Research', '', 'create-research', 1, 1))
        db.execute('INSERT INTO reports VALUES (?,?,?,?,?,?,?)',
                   (item['report_id'], item['research_id'], 'self', 'Report', 'create-report', 1, 1))
        db.execute('''INSERT INTO report_publications
            (report_id,manager_hash,publication_id,revision,generation,projection_hash,local_root_ref)
            VALUES (?,?,?,?,?,?,?)''', (item['report_id'], 'manager-a', 'p', 'r', 1, 'hash', 'root'))
    class Session:
        def get(self, _path, *, query):
            return {'success': True, 'reports': [item], 'next_cursor': None}
    assert discover_local_reports(store, session=Session(), manager_hash='manager-b', profile_id='self', limit=1) == (False, [])
    with store._connect() as db:
        row = db.execute('SELECT report_id,manager_hash,source_kind FROM server_report_pending').fetchone()
    assert (row['report_id'], row['manager_hash'], row['source_kind']) == (item['report_id'], 'manager-b', 'local')


def test_shared_report_discovery_keeps_migrated_research_identity(tmp_path):
    store = LocalResearchCatalog(tmp_path, issuer='https://issuer.test/realm', identity_id='stable', profiles={'self'})
    ensure_publication_table(store)
    item = {**_item('A'), 'research_id': 'research:migrated:' + 'b' * 32}
    class Session:
        def get(self, _path, *, query):
            return {'success': True, 'reports': [item], 'next_cursor': None}
    assert discover_local_reports(store, session=Session(), manager_hash='manager', profile_id='self', limit=1) == (False, [])
    with store._connect() as db:
        row = db.execute('SELECT research_id,report_id,source_kind FROM server_report_pending').fetchone()
        assert tuple(row) == (item['research_id'], item['report_id'], 'local')
