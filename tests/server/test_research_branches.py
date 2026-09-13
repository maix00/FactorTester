import pytest
from server.manager.services.research_catalog import ResearchCatalog


def setup(tmp_path):
    catalog = ResearchCatalog(tmp_path / 'research.sqlite')
    rid = catalog.create_research(owner_ref='alice', title='shared')['research_id']
    catalog.register_report(rid, actor='alice', report_id='report', title='report', profile_ref='self')
    catalog.add_membership(rid, actor='alice', principal_ref='bob', profile_ref='self', role='editor')
    catalog.create_workspace(rid, actor='alice', principal_ref='bob', profile_ref='self', title='bob')
    return catalog, rid


def publish(catalog, branch, actor='alice', generation=1, expected=0):
    return catalog.publish_report_branch('report', branch, actor=actor, profile_ref='self',
                                         expected_generation=expected, expected_revision='' if not expected else 'a' * 64,
                                         generation=generation, revision='a' * 64,
                                         publication_id='p' * 24, storage_server_id='server-one')


def test_report_branch_identity_is_not_profile_name_and_fork_is_versioned(tmp_path):
    catalog, _ = setup(tmp_path)
    first = catalog.reserve_report_branch('report', actor='alice', profile_ref='self', branch_id='main')
    assert first['status'] == 'reserved'
    assert catalog.list_report_branches('report', viewer='bob') == []
    with pytest.raises(ValueError, match='another writer'):
        catalog.reserve_report_branch('report', actor='bob', profile_ref='self', branch_id='main')
    published = publish(catalog, 'main')
    assert published['status'] == 'active'
    bob = catalog.reserve_report_branch('report', actor='bob', profile_ref='self', branch_id='bob-review',
                                        source_branch_id='main', source_generation=1, source_revision='a' * 64)
    assert bob['report_id'] == published['report_id']
    assert bob['principal_ref'] == 'bob' and bob['workspace_id'] != first['workspace_id']
    assert catalog.reserve_report_branch('report', actor='bob', profile_ref='self', branch_id='bob-review',
                                        source_branch_id='main', source_generation=1, source_revision='a' * 64) == bob
    with pytest.raises(ValueError, match='version'):
        catalog.reserve_report_branch('report', actor='bob', profile_ref='self', branch_id='stale',
                                      source_branch_id='main', source_generation=0, source_revision='a' * 64)


def test_branch_writer_and_revocation_are_checked_at_each_write(tmp_path):
    catalog, rid = setup(tmp_path)
    catalog.reserve_report_branch('report', actor='alice', profile_ref='self', branch_id='main')
    with pytest.raises(PermissionError, match='writer Profile'):
        publish(catalog, 'main', actor='bob')
    publish(catalog, 'main')
    with pytest.raises(ValueError, match='conflict'):
        publish(catalog, 'main', generation=2, expected=0)
    assert publish(catalog, 'main')['generation'] == 1  # idempotent retry
    catalog.reserve_report_branch('report', actor='bob', profile_ref='self', branch_id='review')
    catalog.remove_membership(rid, actor='alice', profile_ref='self', principal_ref='bob')
    with pytest.raises(PermissionError, match='exact Profile'):
        publish(catalog, 'review', actor='bob')
    with pytest.raises(PermissionError):
        catalog.list_report_branches('report', viewer='bob')


def test_editor_publication_read_is_bound_to_registered_identity_and_live_grants(tmp_path):
    catalog, rid = setup(tmp_path)
    catalog.reserve_report_branch('report', actor='bob', profile_ref='self', branch_id='review')
    publish(catalog, 'review', actor='bob')
    record = {'report_id': 'report', 'owner_ref': 'bob', 'publication_id': 'p' * 24}
    assert catalog.can_read_publication(record, 'alice')
    assert not catalog.can_read_publication({**record, 'publication_id': 'q' * 24}, 'alice')
    assert not catalog.can_read_publication({**record, 'owner_ref': 'mallory'}, 'alice')
    assert not catalog.can_read_publication(record, 'stranger')
    reports = catalog.list_reports(rid, viewer='alice')
    assert any(b['branch_ref'] == 'review' and b['principal_ref'] == 'bob' for b in reports[0]['branches'])
    catalog.remove_membership(rid, actor='alice', profile_ref='self', principal_ref='bob')
    assert catalog.can_read_publication(record, 'alice')  # historical work remains available to the report owner
    assert not catalog.can_read_publication(record, 'bob')


def test_branch_http_verifies_real_publication_identity_and_version(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from server.manager.http import research_branch_routes as routes
    from server.manager.http.research_catalog_routes import ResearchCatalogRoutesMixin
    catalog, _ = setup(tmp_path)
    catalog.reserve_report_branch('report', actor='bob', profile_ref='self', branch_id='review')
    publication = {'report_id': 'report', 'owner_ref': 'bob', 'profile_ref': 'self',
                   'branch_ref': 'review', 'publication_id': 'p' * 24, 'generation': 1,
                   'projection_hash': 'a' * 64, 'storage_server_id': 'actual-source'}
    index = {'report_id': 'report', 'generation': 1, 'projection_hash': 'a' * 64}
    class Handler(ResearchCatalogRoutesMixin):
        state = SimpleNamespace(research_catalog=catalog)
        def _research_service(self):
            return SimpleNamespace(list_visible=lambda actor: [publication], index=lambda pid, actor: index)
    responses = []
    monkeypatch.setattr(routes, 'json_response', lambda h, body, status=200: responses.append((body, status)))
    request = SimpleNamespace(path='/api/research/reports/report/branches/review/publish')
    payload = {'profile_ref': 'self', 'publication_id': 'p' * 24, 'expected_generation': 0,
               'expected_revision': '', 'generation': 999, 'revision': 'forged', 'storage_server_id': 'forged'}
    publication['owner_ref'] = 'mallory'
    with pytest.raises(PermissionError):
        Handler()._post_report_branch_route(request, 'bob', payload)
    publication['owner_ref'] = 'bob'
    index['generation'] = 2
    with pytest.raises(ValueError, match='changed during verification'):
        Handler()._post_report_branch_route(request, 'bob', payload)
    index['generation'] = 1
    assert Handler()._post_report_branch_route(request, 'bob', payload)
    branch = responses[-1][0]['branch']
    assert branch['generation'] == 1 and branch['storage_server_id'] == 'actual-source'


def test_branch_http_agent_cannot_choose_another_profile():
    from types import SimpleNamespace
    from server.manager.http.research_branch_routes import ResearchBranchRoutesMixin
    handler = ResearchBranchRoutesMixin()
    handler.state = SimpleNamespace(session_authentication=lambda token: 'agent',
                                    agent_session_matches=lambda token, profile, claim: profile == 'bound')
    handler._bearer_token = lambda: 'test-token'
    handler.headers = {'X-FactorTester-Agent-Claim': 'claim'}
    handler._require_branch_profile_actor('bound')
    with pytest.raises(PermissionError, match='another Profile'):
        handler._require_branch_profile_actor('other')
