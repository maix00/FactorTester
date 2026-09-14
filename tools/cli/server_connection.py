"""Resolve a stable server identity using the selected Manager's directory."""
from __future__ import annotations
from urllib.parse import urlsplit
from tools.cli.http import ClientConfig, HttpSession


def discover_server(seed: ClientConfig, server_id: str) -> ClientConfig:
    info = HttpSession(seed.base_url).request('GET', '/api/server/network-info',
        extra_headers={'X-FactorTester-Client': 'cli'})
    if info.get('server_id') == server_id:
        return seed
    targets = info.get('online_public_server_targets', []) + info.get('internal_server_targets', [])
    endpoints = []
    for target in targets:
        if target.get('server_id') != server_id or target.get('online') is not True:
            continue
        if target.get('endpoint'):
            endpoints.append(str(target['endpoint']).rstrip('/'))
        elif target.get('manager_port'):
            for address in target.get('addresses', []):
                host = '[' + address + ']' if ':' in address else address
                endpoints.append(f"http://{host}:{int(target['manager_port'])}")
    for endpoint in dict.fromkeys(endpoints):
        parsed = urlsplit(endpoint)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
            continue
        # No seed credential is passed to a different endpoint. Confirm the
        # destination's identity before adopting its server-provided address.
        try:
            actual = HttpSession(endpoint, timeout=5).request('GET', '/api/server/network-info',
                extra_headers={'X-FactorTester-Client': 'cli'})
        except (OSError, RuntimeError):
            continue
        if actual.get('server_id') == server_id:
            return ClientConfig(endpoint)
    raise ValueError('服务器不可达或身份不匹配；请在客户端选择并信任该服务器后重试')
