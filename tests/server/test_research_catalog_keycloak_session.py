from types import SimpleNamespace

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
