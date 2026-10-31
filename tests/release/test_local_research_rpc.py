from concurrent.futures import ThreadPoolExecutor

import pytest

from tools.cli.release.research_reporting.local_rpc import SCHEMA, LocalResearchRPC


@pytest.mark.parametrize('overrides', [
    {'visitor_login': True}, {'role': 'visitor'}, {'authentication': 'agent'},
    {'username': ''}, {'username': None}, {'tr_identity_id': 'someone-else'},
    {'keycloak_subject': 'another-subject'}, {'keycloak_issuer': 'https://other/realm'},
])
def test_publication_transport_rejects_non_user_or_changed_identity(monkeypatch, overrides):
    from tools.cli.release.research_reporting import local_publication
    identity = {'username': 'alice', 'keycloak_issuer': 'https://id.test/realm',
                'keycloak_subject': 'subject', 'tr_identity_id': 'stable', **overrides}

    class Session:
        def __init__(self, *args, **kwargs): pass
        def import_cookies(self, cookies): pass
        def get(self, path):
            assert path == '/api/session'
            return identity

    monkeypatch.setattr(local_publication, 'HttpSession', Session)
    manager = {'endpoint': 'https://manager.test', 'subject': 'subject', 'token': '',
               'certificate_pem': '', 'cookies': []}
    with pytest.raises(PermissionError):
        local_publication.manager_session({'issuer': 'https://id.test/realm', 'identity_id': 'stable'}, manager)


def test_rpc_uses_only_native_binding_and_preserves_idempotency(tmp_path):
    rpc = LocalResearchRPC(tmp_path, issuer='https://id.test/realm/', identity_id='stable',
                           profiles=[{'profile_id': 'self', 'display_name': 'Self'}])
    capability = rpc.request({'action': 'capabilities'})
    assert capability['schema'] == SCHEMA
    assert capability['binding'] == {'issuer': 'https://id.test/realm', 'identity_id': 'stable'}
    message = {'action': 'create', 'profile_id': 'self', 'title': ' R ',
               'description': 'a\nb', 'operation_id': 'op-1'}
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: rpc.request(message), range(8)))
    assert len({item['research']['research_id'] for item in results}) == 1
    row = results[0]['research']
    assert row['title'] == 'R' and row['description'] == 'a\nb'
    page = rpc.request({'action': 'list', 'profile_id': 'self', 'limit': 1, 'offset': 0})
    assert page['researches'] == [row] and page['next_offset'] is None
    assert rpc.request({'action': 'get', 'profile_id': 'self', 'research_id': row['research_id']})['research'] == row


def test_rpc_rejects_web_identity_injection_and_unauthorized_profile(tmp_path):
    rpc = LocalResearchRPC(tmp_path, issuer='https://id.test/realm', identity_id='stable',
                           profiles=[{'profile_id': 'self', 'display_name': 'Self'}])
    with pytest.raises(ValueError):
        rpc.request({'action': 'capabilities', 'identity_id': 'other'})
    with pytest.raises(ValueError):
        rpc.request({'action': 'list', 'profile_id': 'self', 'limit': True, 'offset': 0})
    with pytest.raises(PermissionError):
        rpc.request({'action': 'list', 'profile_id': 'other', 'limit': 20, 'offset': 0})
    with pytest.raises(ValueError):
        rpc.request({'action': 'create', 'profile_id': 'self', 'title': 'bad\x00title',
                     'description': '', 'operation_id': 'op-1'})


def test_rpc_rejects_ambiguous_native_profiles(tmp_path):
    with pytest.raises(ValueError):
        LocalResearchRPC(tmp_path, issuer='https://id.test/realm', identity_id='stable',
                         profiles=[{'profile_id': 'self', 'display_name': 'A'},
                                   {'profile_id': 'self', 'display_name': 'B'}])


def test_research_directory_pages_detect_concurrent_changes(tmp_path):
    rpc = LocalResearchRPC(tmp_path, issuer='https://id.test/realm', identity_id='stable',
                           profiles=[{'profile_id': 'self', 'display_name': 'Self'}])
    for number in range(2):
        rpc.request({'action': 'create', 'profile_id': 'self', 'title': str(number),
                     'description': '', 'operation_id': f'op-{number}'})
    request = {'action': 'list_researches', 'profile_id': 'self', 'limit': 1, 'offset': 0, 'expected_revision': None}
    first = rpc.request(request)
    second = rpc.request({**request, 'offset': first['next_offset'], 'expected_revision': first['revision']})
    assert len(first['researches'] + second['researches']) == 2
    assert second['next_offset'] is None
    rpc.request({'action': 'create', 'profile_id': 'self', 'title': 'new', 'description': '', 'operation_id': 'op-new'})
    assert rpc.request({**request, 'offset': first['next_offset'], 'expected_revision': first['revision']}) == {
        'success': False, 'code': 'local_research_listing_changed'}
    assert rpc.request(request)['revision'] > first['revision']
    with pytest.raises(ValueError):
        rpc.request({**request, 'offset': 1})
    with pytest.raises(PermissionError):
        rpc.request({**request, 'profile_id': 'other'})
    with rpc.store._connect() as db:
        assert 'researches_profile_page' in [row['name'] for row in db.execute('PRAGMA index_list(researches)')]


def test_profile_report_directory_is_bounded_and_profile_scoped(tmp_path):
    rpc = LocalResearchRPC(tmp_path, issuer='https://id.test/realm', identity_id='stable',
                           profiles=[{'profile_id': 'self', 'display_name': 'Self'},
                                     {'profile_id': 'work', 'display_name': 'Work'}])
    created = {}
    for profile in ('self', 'work'):
        research = rpc.request({'action': 'create', 'profile_id': profile, 'title': 'Research ' + profile,
                                'description': 'description is loaded only when opened', 'operation_id': 'research-' + profile})['research']
        for number in range(2):
            row = rpc.request({'action': 'create_report', 'profile_id': profile, 'research_id': research['research_id'],
                               'title': f'Report {profile} {number}', 'operation_id': f'{profile}-{number}'})['report']
            created[row['report_id']] = (profile, research)
    request = {'action': 'list_profile_reports', 'profile_id': 'self', 'limit': 1, 'offset': 0, 'expected_revision': None}
    first = rpc.request(request)
    second = rpc.request({**request, 'offset': first['next_offset'], 'expected_revision': first['revision']})
    rows = first['reports'] + second['reports']
    assert len(rows) == 2 and second['next_offset'] is None
    assert all('description' not in row['research'] for row in rows)
    assert all(created[row['report_id']][0] == 'self' and
               {key: value for key, value in created[row['report_id']][1].items() if key != 'description'} == row['research']
               for row in rows)
    assert len({row['report_id'] for row in rows}) == 2
    with rpc.store._connect() as db:
        db.execute('UPDATE reports SET title=? WHERE report_id=?', ('changed', rows[0]['report_id']))
    assert rpc.request({**request, 'offset': first['next_offset'], 'expected_revision': first['revision']}) == {
        'success': False, 'code': 'local_research_listing_changed'}
    fresh = rpc.request(request)
    assert fresh['success'] is True and fresh['revision'] > first['revision']
    with pytest.raises(ValueError):
        rpc.request({**request, 'offset': 1})
    with pytest.raises(PermissionError):
        rpc.request({**request, 'profile_id': 'other'})
    with pytest.raises(ValueError):
        rpc.request({**request, 'limit': True})
    with rpc.store._connect() as db:
        indexes = [row['name'] for row in db.execute('PRAGMA index_list(reports)')]
    assert 'reports_profile_page' in indexes
    foreign_research = next(value[1]['research_id'] for value in created.values() if value[0] == 'work')
    with rpc.store._connect() as db:
        db.execute('UPDATE reports SET research_id=?,created_at=? WHERE report_id=?',
                   (foreign_research, 99999999999, rows[0]['report_id']))
    with pytest.raises(ValueError, match='mismatched Research identity'):
        rpc.request(request)


def test_local_report_uses_existing_report_tree_and_retry_recovers(tmp_path, monkeypatch):
    from tools.cli.release.research_reporting import workspace
    from tools.cli.release.research_reporting.authoring.tree_projection import load_snapshot
    from tools.cli.release.research_reporting.report_workspace_identity import report_workspace_id_for

    rpc = LocalResearchRPC(tmp_path, issuer='https://id.test/realm', identity_id='stable',
                           profiles=[{'profile_id': 'self', 'display_name': 'Self'}])
    research = rpc.request({'action': 'create', 'profile_id': 'self', 'title': 'Research',
                            'description': '', 'operation_id': 'research-op'})['research']
    request = {'action': 'create_report', 'profile_id': 'self', 'research_id': research['research_id'],
               'title': 'Report', 'operation_id': 'report-op'}
    original = workspace.initialize_report_workspace
    monkeypatch.setattr(workspace, 'initialize_report_workspace', lambda **_: (_ for _ in ()).throw(OSError('interrupted')))
    with pytest.raises(OSError):
        rpc.request(request)
    listing = {'action': 'list_reports', 'profile_id': 'self', 'research_id': research['research_id'], 'limit': 20, 'offset': 0}
    assert rpc.request(listing)['reports'] == []
    monkeypatch.setattr(workspace, 'initialize_report_workspace', original)
    with ThreadPoolExecutor(max_workers=4) as pool:
        values = list(pool.map(lambda _: rpc.request(request)['report'], range(4)))
    assert all(value == values[0] for value in values)
    assert rpc.request(listing)['reports'] == [values[0]]
    root = rpc.store.workspace_root / 'research' / report_workspace_id_for(values[0]['report_id'])
    assert load_snapshot(package_root=root, branch_id='main')['head']['report_id'] == values[0]['report_id']
    assert (root / '.git').is_dir()
    import subprocess
    before = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    (root / 'private-draft.txt').write_text('unfinished draft', encoding='utf-8')
    assert rpc.request(request)['report'] == values[0]
    after = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    assert before == after
    assert 'private-draft.txt' in subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain'], text=True)
    (root / 'private-draft.txt').unlink()
    read = {'action': 'get_report', 'profile_id': 'self', 'research_id': research['research_id'],
            'report_id': values[0]['report_id']}
    result = rpc.request(read)
    assert result['report'] == values[0]
    assert result['index']['report_id'] == values[0]['report_id']
    assert result['index']['chapters'] == []
    assert 'paths' not in result['index']
    edit = {'action': 'add_report_component', 'profile_id': 'self', 'research_id': research['research_id'],
            'report_id': values[0]['report_id'], 'component_id': 'chapter-1', 'kind': 'chapter',
            'parent_id': '', 'title': 'Chapter', 'body': '', **result['version']}
    next_version = rpc.request(edit)['version']
    assert next_version['generation'] == result['version']['generation'] + 1
    assert rpc.request({**edit, 'component_id': 'chapter-2'}) == {'success': False, 'code': 'local_report_version_conflict'}
    paragraph = {**edit, **next_version, 'component_id': 'entry-1', 'kind': 'entry',
                 'parent_id': 'chapter-1', 'title': '', 'body': 'First\nsecond'}
    latest = rpc.request(paragraph)['version']
    chapter = rpc.request({'action': 'get_report_chapter', 'profile_id': 'self',
        'research_id': research['research_id'], 'report_id': values[0]['report_id'], 'chapter_id': 'chapter-1'})
    assert chapter['version'] == latest
    assert [(x['kind'], x['body']) for x in chapter['chapter']['components']] == [('chapter', ''), ('entry', 'First\nsecond')]
    assert subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain'], text=True).strip() == ''
    other = LocalResearchRPC(tmp_path, issuer='https://id.test/realm', identity_id='other',
                             profiles=[{'profile_id': 'self', 'display_name': 'Other'}])
    with pytest.raises(ValueError):
        other.request(listing)
    with pytest.raises(ValueError):
        other.request(read)
    with pytest.raises(ValueError):
        rpc.request({**request, 'title': 'Different'})


def test_automatic_sync_is_bounded_and_only_visits_explicit_publications(tmp_path, monkeypatch):
    import hashlib
    from tools.cli.release.research_reporting import local_auto_sync
    from tools.cli.release.research_reporting.local_publication import ensure_publication_table

    manager = {'endpoint': 'https://manager.test', 'subject': 'subject', 'token': '', 'certificate_pem': '', 'cookies': []}
    rpc = LocalResearchRPC(tmp_path, issuer='https://id.test/realm', identity_id='stable',
                           profiles=[{'profile_id': 'self', 'display_name': 'Self'}], manager=manager)
    research = rpc.request({'action':'create', 'profile_id':'self', 'title':'R', 'description':'', 'operation_id':'r'})['research']
    ids = []
    ensure_publication_table(rpc.store)
    for i in range(6):
        report = rpc.request({'action':'create_report', 'profile_id':'self', 'research_id':research['research_id'], 'title':f'R{i}', 'operation_id':f'create-{i}'})['report']
        version = rpc.request({'action':'get_report', 'profile_id':'self', 'research_id':research['research_id'], 'report_id':report['report_id']})['version']
        if i < 5:
            ids.append(report['report_id'])
            with rpc.store._connect() as db:
                db.execute('INSERT INTO report_publications (report_id, manager_hash, publication_id, revision, generation, projection_hash, local_root_ref) VALUES (?, ?, ?, ?, ?, ?, ?)',
                    (report['report_id'], hashlib.sha256(manager['endpoint'].encode()).hexdigest(), 'p-'+'a'*64, 'rev', version['generation'], 'f'*64, version['root_ref']))
        else:
            # A receipt for another Manager does not authorize synchronization here.
            with rpc.store._connect() as db:
                db.execute('INSERT INTO report_publications (report_id, manager_hash, publication_id, revision, generation, projection_hash, local_root_ref) VALUES (?, ?, ?, ?, ?, ?, ?)',
                    (report['report_id'], hashlib.sha256(b'https://other-manager.test').hexdigest(), 'p-'+'b'*64, 'rev', version['generation'], 'f'*64, version['root_ref']))
    visited = []
    monkeypatch.setattr(local_auto_sync, 'manager_session', lambda *_args: (manager['endpoint'], object()))
    monkeypatch.setattr(local_auto_sync, '_remote', lambda _session, _research, report, **_kwargs: (visited.append(report) or {
        'publication': {'revision':'rev', 'publication_id': 'p-'+'a'*64}, 'authoring': {}}))
    request = {'action':'sync_reports', 'profile_id':'self', 'after_report_id':'', 'limit':2}
    all_rows = []
    while True:
        result = rpc.request(request); all_rows.extend(result['reports'])
        if result['next_report_id'] is None: break
        request['after_report_id'] = result['next_report_id']
    assert visited == sorted(ids) and [row['report_id'] for row in all_rows] == sorted(ids)
    assert all(row['status'] == 'unchanged' for row in all_rows)
    with rpc.store._connect() as db:
        plan = db.execute('EXPLAIN QUERY PLAN ' + local_auto_sync._PUBLICATION_PAGE,
            (hashlib.sha256(manager['endpoint'].encode()).hexdigest(), 'self', '', 3)).fetchall()
    assert any('report_publications_manager_report' in row['detail'] for row in plan)
    assert not any('TEMP B-TREE' in row['detail'] for row in plan)


def test_sync_receipt_recovery_does_not_overwrite_concurrent_receipt(tmp_path, monkeypatch):
    import hashlib
    from tools.cli.release.research_reporting import local_auto_sync
    from tools.cli.release.research_reporting.authoring.tree_projection import load_snapshot
    from tools.cli.release.research_reporting.public_research.projection import build_upload_projection
    from tools.cli.release.research_reporting.local_publication import ensure_publication_table

    manager = {'endpoint': 'https://manager.test', 'subject': 'subject', 'token': '', 'certificate_pem': '', 'cookies': []}
    rpc = LocalResearchRPC(tmp_path, issuer='https://id.test/realm', identity_id='stable',
                           profiles=[{'profile_id': 'self', 'display_name': 'Self'}], manager=manager)
    research = rpc.request({'action':'create', 'profile_id':'self', 'title':'R', 'description':'', 'operation_id':'r'})['research']
    report = rpc.request({'action':'create_report', 'profile_id':'self', 'research_id':research['research_id'],
                          'title':'Report', 'operation_id':'report'})['report']
    version = rpc.request({'action':'get_report', 'profile_id':'self', 'research_id':research['research_id'],
                           'report_id':report['report_id']})['version']
    _report, root = rpc.store._report_root('self', research['research_id'], report['report_id'])
    digest = build_upload_projection(load_snapshot(package_root=root, branch_id='main'))['projection_hash']
    ensure_publication_table(rpc.store)
    with rpc.store._connect() as db:
        db.execute('INSERT INTO report_publications (report_id, manager_hash, publication_id, revision, generation, projection_hash, local_root_ref) VALUES (?, ?, ?, ?, ?, ?, ?)',
                   (report['report_id'], hashlib.sha256(manager['endpoint'].encode()).hexdigest(),
                    'p-'+'a'*64, 'old', 999, 'f'*64, 'old-root'))
    monkeypatch.setattr(local_auto_sync, 'manager_session', lambda *_args: (manager['endpoint'], object()))
    monkeypatch.setattr(local_auto_sync, '_remote', lambda *_args, **_kwargs: {
        'publication': {'revision':'remote', 'publication_id':'p-'+'a'*64, 'projection_hash':'e'*64},
        'authoring': version})
    request = {'action':'sync_reports', 'profile_id':'self', 'after_report_id':'', 'limit':2}
    assert rpc.request(request)['reports'][0]['status'] == 'conflict'
    def concurrent_update(*_args, **_kwargs):
        with rpc.store._connect() as db:
            db.execute('UPDATE report_publications SET revision=? WHERE report_id=?', ('newer', report['report_id']))
        return {'publication': {'revision':'remote', 'publication_id':'p-'+'a'*64, 'projection_hash':digest},
                'authoring': version}
    monkeypatch.setattr(local_auto_sync, '_remote', concurrent_update)
    result = rpc.request(request)
    assert result['reports'][0]['status'] == 'conflict'
    with rpc.store._connect() as db:
        assert db.execute('SELECT revision FROM report_publications').fetchone()['revision'] == 'newer'
