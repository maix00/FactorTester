"""Retired ACL publication routes cannot recreate local authorization."""
from types import SimpleNamespace
import pytest
from server.manager.http.public_research_routes import PublicResearchRoutesMixin
from server.manager.http.write_routes import WriteRoutesMixin

@pytest.mark.parametrize("path", ["/api/research-publications/publish", "/api/research-publications/settings", "/api/research-publications/revoke"])
def test_legacy_publication_writes_are_gone(path, monkeypatch):
    responses = []
    monkeypatch.setattr("server.manager.http.write_routes.json_response", lambda _self, value, status: responses.append((value, status)))
    class Handler(WriteRoutesMixin):
        def _redirect_plain_http_to_https(self): return False
        def _proxy_keycloak(self, *args, **kwargs): return False
        def _dispatch_execution_node(self, *args): return False
        def _public_login_gate(self, *args, **kwargs): return True
        def _json_body(self, *args): raise AssertionError("retired request must not mutate state")
    handler = Handler()
    handler.path = path
    handler.do_POST()
    assert responses[0][1] == 410
    assert responses[0][0]["code"] == "legacy_research_publication_retired"

def test_legacy_publication_settings_read_is_gone(monkeypatch):
    responses = []
    monkeypatch.setattr("server.manager.http.public_research_routes.json_response", lambda _self, value, status: responses.append((value, status)))
    class Handler(PublicResearchRoutesMixin):
        def _research_service(self): return None
    assert Handler()._get_public_research_routes(SimpleNamespace(path="/api/research-publications/settings", query=""))
    assert responses[0][1] == 410
