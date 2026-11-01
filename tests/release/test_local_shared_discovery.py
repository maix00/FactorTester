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
