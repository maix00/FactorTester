from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

from server.manager.http import job_proxy_routes
from server.manager.http.gateway import GatewayResponse


@pytest.mark.parametrize('method,forwarded', [('DELETE', True), ('PUT', False), ('GET', False)])
def test_deleted_family_only_allows_delete_retry(monkeypatch, method, forwarded):
    calls = []
    monkeypatch.setattr('server.manager.services.factor_family_current.ensure_current_family', lambda *a, **k: False)
    monkeypatch.setattr(job_proxy_routes, 'json_response', lambda handler, body, code: calls.append(code))
    response = GatewayResponse(200, b'{"success": true}', 'application/json')
    state = SimpleNamespace(server_id='local', route_for=lambda **k: 'route',
                            route_request=lambda *a, **k: calls.append(k) or response)
    handler = SimpleNamespace(state=state, headers={}, _session=lambda: {'username': 'alice'},
                              _is_local_agent_request=lambda: False,
                              _send_gateway_response=lambda *a, **k: None)
    assert job_proxy_routes.JobProxyRoutesMixin._proxy_authenticated_local_service(
        handler, urlparse('/api/factor-library/families/custom/CA'), method=method)
    if forwarded:
        assert calls[0]['principal'] == 'alice'
        assert calls[0]['method'] == 'DELETE'
    else:
        assert calls == [404]
