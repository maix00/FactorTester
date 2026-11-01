from types import SimpleNamespace

import pytest

from server.manager.http import research_catalog_routes


def test_research_all_scope_does_not_query_the_admin_directory(monkeypatch):
    responses, calls = [], []
    class Service:
        def list_researches(self, **kwargs):
            calls.append(kwargs)
            return []
    class Handler(research_catalog_routes.ResearchCatalogRoutesMixin):
        state = SimpleNamespace(research_catalog=Service())
        def _session(self):
            return {"username": "alice", "keycloak_subject": "s"}
        def _subordinate_users(self, session):
            raise AssertionError("all scope must not fetch a Keycloak directory")
    monkeypatch.setattr(research_catalog_routes, "json_response",
                        lambda _handler, body, status=200: responses.append((body, status)))
    assert Handler()._get_research_catalog_routes(SimpleNamespace(path="/api/research", query="scope=all"))
    assert responses[0][1] == 200
    assert calls[0]["subordinate_refs"] == []


def test_subordinate_scope_passes_verified_session_not_user_supplied_name(monkeypatch):
    responses, calls = [], []
    session = {"username": "alice", "keycloak_subject": "s", "keycloak_groups": ["/scoped"]}
    class Service:
        def list_researches(self, **kwargs):
            calls.append(kwargs)
            return []
    class Handler(research_catalog_routes.ResearchCatalogRoutesMixin):
        state = SimpleNamespace(research_catalog=Service())
        def _session(self):
            return session
        def _subordinate_users(self, value):
            assert value is session
            return [{"username": "bob"}]
    monkeypatch.setattr(research_catalog_routes, "json_response",
                        lambda _handler, body, status=200: responses.append((body, status)))
    handler = Handler()
    assert handler._get_research_catalog_routes(SimpleNamespace(path="/api/research", query="scope=subordinates"))
    assert responses[0][1] == 200 and calls[0]["subordinate_refs"] == ["bob"]
    try:
        handler._research_catalog_subordinate_refs("mallory")
    except PermissionError:
        pass
    else:
        raise AssertionError("unverified viewer must not reuse the session's managed subtree")


def test_research_principal_picker_uses_native_verified_keycloak_session(monkeypatch):
    responses = []
    session = {"username": "alice", "keycloak_subject": "s", "parent_username": "parent",
               "keycloak_groups": ["/scoped"]}
    class Handler(research_catalog_routes.ResearchCatalogRoutesMixin):
        state = SimpleNamespace(research_catalog=object())
        def _session(self):
            return session
        def _subordinate_users(self, value):
            assert value is session
            return [{"username": "bob"}]
    monkeypatch.setattr(research_catalog_routes, "json_response",
                        lambda _handler, body, status=200: responses.append((body, status)))
    handler = Handler()
    assert handler._get_research_catalog_routes(SimpleNamespace(path="/api/research/principals", query=""))
    assert responses[-1][0]["principals"] == [{"principal_ref": "bob", "label": "bob"}]
    assert handler._get_research_catalog_routes(SimpleNamespace(path="/api/research/principals", query="relation=superiors"))
    assert responses[-1][0]["principals"] == [{"principal_ref": "parent", "label": "parent"}]
    assert handler._research_catalog_superior_refs("mallory") == []


def test_normal_user_principal_picker_does_not_gain_admin_directory(monkeypatch):
    responses = []
    class Handler(research_catalog_routes.ResearchCatalogRoutesMixin):
        state = SimpleNamespace(research_catalog=object())
        def _session(self):
            return {"username": "alice", "keycloak_subject": "s"}
        def _subordinate_users(self, _session):
            raise PermissionError("no Keycloak managed group")
    monkeypatch.setattr(research_catalog_routes, "json_response",
                        lambda _handler, body, status=200: responses.append((body, status)))
    assert Handler()._get_research_catalog_routes(SimpleNamespace(path="/api/research/principals", query=""))
    assert responses[-1][0]["principals"] == []


def test_owned_sync_cursor_is_opaque_and_bound_to_verified_identity(monkeypatch):
    from urllib.parse import urlencode
    responses, calls = [], []
    session = {'username': 'alice', 'tr_identity_id': 'alice-stable'}
    class Service:
        def owned_sync_page(self, **kwargs):
            calls.append(kwargs)
            return {'researches': [], 'next_cursor': {'updated_at': 3, 'research_id': 'denied-secret'}}
    class Handler(research_catalog_routes.ResearchCatalogRoutesMixin):
        state = SimpleNamespace(research_catalog=Service())
        def _session(self): return session
    monkeypatch.setattr(research_catalog_routes, 'json_response',
                        lambda _handler, body, status=200: responses.append((body, status)))
    handler = Handler()
    assert handler._get_research_catalog_routes(SimpleNamespace(path='/api/research/owned-sync', query='limit=2'))
    token = responses[-1][0]['next_cursor']
    assert responses[-1][1] == 200 and 'denied-secret' not in token
    assert handler._get_research_catalog_routes(SimpleNamespace(path='/api/research/owned-sync', query=urlencode({'cursor':token})))
    assert calls[-1]['after_ref'] == 'denied-secret'
    session['tr_identity_id'] = 'another-user'
    assert handler._get_research_catalog_routes(SimpleNamespace(path='/api/research/owned-sync', query=urlencode({'cursor':token})))
    assert responses[-1][1] == 400 and len(calls) == 2


@pytest.mark.parametrize("path", ["/api/research", "/api/research/reports"])
@pytest.mark.parametrize("scope", ["mine", "all", "subordinates"])
def test_research_lists_use_verified_session_for_directory(monkeypatch, path, scope):
    """The live Manager directory expects claims, never a bare username."""
    from server.manager.http import job_list_routes
    from server.identity import keycloak_directory

    session = {"username": "alice", "keycloak_subject": "subject", "keycloak_groups": ["/scope"]}
    calls, responses = [], []

    class Service:
        def list_researches(self, **kwargs):
            calls.append(kwargs)
            return []

        def list_reports_for_scope(self, **kwargs):
            calls.append(kwargs)
            return []

    class Handler(research_catalog_routes.ResearchCatalogRoutesMixin, job_list_routes.JobListRoutesMixin):
        state = SimpleNamespace(research_catalog=Service())

        def _session(self):
            return session

        def _research_catalog_publication_branches(self, reports, viewer):
            return reports

    def groups(claims):
        assert claims is session
        return ["/scope"]

    monkeypatch.setattr(job_list_routes, "current_administrative_groups", groups)
    monkeypatch.setattr(job_list_routes, "current_manager_role", lambda claims, role: False)
    monkeypatch.setattr(keycloak_directory, "managed_users_for_claims",
                        lambda **kwargs: [{"username": "alice"}, {"username": "bob"}])
    monkeypatch.setattr(research_catalog_routes, "json_response",
                        lambda _handler, body, status=200: responses.append((body, status)))

    assert Handler()._get_research_catalog_routes(SimpleNamespace(path=path, query=f"scope={scope}"))
    assert responses[0][1] == 200
    assert calls[0]["viewer"] == "alice"
    assert calls[0]["subordinate_refs"] == (["bob"] if scope == "subordinates" else [])


def test_owned_report_cursor_is_bound_to_user_and_research(monkeypatch):
    from urllib.parse import urlencode
    from types import SimpleNamespace
    from server.manager.http import research_catalog_routes
    replies, calls = [], []
    session = {'username': 'alice', 'keycloak_subject': 'subject', 'tr_identity_id': 'stable'}
    class Service:
        def owned_report_sync_page(self, **kwargs):
            calls.append(kwargs)
            return {'reports': [], 'next_cursor': 'private-report'}
    class Handler(research_catalog_routes.ResearchCatalogRoutesMixin):
        state = SimpleNamespace(research_catalog=Service())
        def _session(self): return session
        def _refresh_research_catalog(self, _viewer): raise AssertionError('bounded discovery must not refresh')
    monkeypatch.setattr(research_catalog_routes, 'json_response', lambda _handler, body, status=200: replies.append((body, status)))
    handler = Handler()
    def get(query):
        return handler._get_research_catalog_routes(SimpleNamespace(path='/api/research/owned-report-sync', query=urlencode(query)))
    assert get({'research_id': 'research-1', 'limit': 2})
    token = replies[-1][0]['next_cursor']
    assert replies[-1][1] == 200 and 'private-report' not in token
    assert get({'research_id': 'research-1', 'cursor': token}) and calls[-1]['after_ref'] == 'private-report'
    assert get({'research_id': 'research-2', 'cursor': token}) and replies[-1][1] == 400
    session['tr_identity_id'] = 'another'
    assert get({'research_id': 'research-1', 'cursor': token}) and replies[-1][1] == 400
    assert len(calls) == 2
