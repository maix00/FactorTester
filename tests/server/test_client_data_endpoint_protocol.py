"""Control transport must not change the data listener's TLS contract."""
from types import SimpleNamespace

import pytest

from server.manager.http.request_security import RequestSecurityMixin


@pytest.mark.parametrize(('origin', 'configured', 'expected'), [
    ('http://127.0.0.1:17998', 'https://example.test:7997', 'https://127.0.0.1:7997'),
    ('http://localhost:17998', 'https://example.test:7997', 'https://localhost:7997'),
    ('https://example.test:7998', 'https://example.test:7997', 'https://example.test:7997'),
    ('http://127.0.0.1:7998', 'http://localhost:7997', 'http://127.0.0.1:7997'),
    ('http://untrusted.test:7998', 'https://example.test:7997', 'https://example.test:7997'),
])
def test_access_uses_configured_data_protocol_and_permitted_request_host(origin, configured, expected):
    handler = RequestSecurityMixin()
    handler.state = SimpleNamespace(public_server=True, data_plane_process_config=SimpleNamespace(
        client_data_endpoint=configured,
        client_control_endpoint='https://example.test:7998',
        client_port=7997,
    ))
    handler._request_origin = lambda: origin
    access = {'path': '/v1/transfers/test/download', 'bearer': 'test-only'}
    result = handler._rewrite_client_data_access(access)
    assert result['url'] == expected + access['path']
    assert result['data_endpoint'] == expected
    assert result['bearer'] == access['bearer']
    assert 'url' not in access
