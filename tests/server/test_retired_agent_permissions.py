from types import SimpleNamespace
from urllib.parse import urlparse
from server.manager.http.agent_app_routes import AgentAppServerRoutesMixin


def test_retired_permission_api_cannot_read_or_write_store(monkeypatch):
    import server.manager.http.agent_app_routes as routes
    replies = []
    monkeypatch.setattr(routes, 'json_response', lambda handler, payload, status: replies.append((payload, status)))
    handler = AgentAppServerRoutesMixin()
    for operation in (handler._get_agent_permission_routes, handler._post_agent_app_routes):
        assert operation(urlparse('/api/admin/agent-permissions'))
    assert [status for _, status in replies] == [410, 410]
    assert all(body['code'] == 'keycloak_managed_permissions' for body, _ in replies)
