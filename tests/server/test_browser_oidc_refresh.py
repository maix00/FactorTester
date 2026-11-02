"""Browser refresh rotates once across concurrent requests; bearer auth stays explicit."""
import base64
import json
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from server.identity import manager_oidc
from server.manager.http.request_security import RequestSecurityMixin


def token(exp):
    payload = base64.urlsafe_b64encode(json.dumps({'exp': exp}).encode()).decode().rstrip('=')
    return 'header.' + payload + '.signature'


def test_concurrent_refresh_uses_one_rotation(monkeypatch):
    calls = []
    monkeypatch.setattr(manager_oidc, 'oidc_settings', lambda: {
        'base_url': 'https://identity', 'realm': 'tr', 'client_id': 'manager', 'client_secret': 'test'})
    class Client:
        def __init__(self, *a, **k): pass
        def refresh(self, value):
            calls.append(value)
            time.sleep(.02)
            return {'access_token': 'new-access', 'refresh_token': 'rotated', 'refresh_expires_in': 600}
    monkeypatch.setattr(manager_oidc, 'OIDCClient', Client)
    monkeypatch.setattr(manager_oidc, 'keycloak_session', lambda _, **kw: {'keycloak_subject': 'alice'})
    with ThreadPoolExecutor(max_workers=8) as pool:
        values = list(pool.map(lambda _: manager_oidc.refresh_browser_tokens('unique-refresh-concurrent'), range(8)))
    assert calls == ['unique-refresh-concurrent']
    assert all(v['access_token'] == 'new-access' for v in values)


def test_expired_cookie_refreshes_but_explicit_bearer_does_not(monkeypatch):
    calls = []
    monkeypatch.setattr(manager_oidc, 'refresh_browser_tokens', lambda value: calls.append(value) or {
        'access_token': 'renewed', 'refresh_token': 'rotated', 'refresh_expires_in': 600})
    h = RequestSecurityMixin()
    h._has_secure_ui_transport = lambda: True
    h._session_cookie = lambda value, **_: 'access=' + value
    h._refresh_cookie = lambda value, **_: 'refresh=' + value
    h.headers = {'Cookie': 'ft-manager-session=' + token(time.time()-1) + '; tr-oidc-refresh=refresh'}
    assert h._bearer_token() == 'renewed'
    assert h._bearer_token() == 'renewed'
    assert calls == ['refresh']
    h2 = RequestSecurityMixin()
    h2.headers = {**h.headers, 'Authorization': 'Bearer explicit'}
    assert h2._bearer_token() == 'explicit'
    assert calls == ['refresh']


def test_refresh_rejects_unverified_identity(monkeypatch):
    monkeypatch.setattr(manager_oidc, 'oidc_settings', lambda: {
        'base_url': 'https://identity', 'realm': 'tr', 'client_id': 'manager', 'client_secret': 'test'})
    monkeypatch.setattr(manager_oidc, 'OIDCClient', lambda *a, **k: SimpleNamespace(
        refresh=lambda _: {'access_token': 'revoked', 'refresh_token': 'other'}))
    monkeypatch.setattr(manager_oidc, 'keycloak_session', lambda _, **kw: None)
    with pytest.raises(PermissionError):
        manager_oidc.refresh_browser_tokens('unique-refresh-revoked')


def test_idle_browser_can_refresh_after_access_cookie_expired(monkeypatch):
    monkeypatch.setattr(manager_oidc, 'refresh_browser_tokens', lambda _: {
        'access_token': 'renewed', 'refresh_token': 'rotated', 'refresh_expires_in': 600})
    h = RequestSecurityMixin()
    h.headers = {'Cookie': 'tr-oidc-refresh=still-active'}
    h._has_secure_ui_transport = lambda: True
    h._session_cookie = lambda value, **_: 'access=' + value
    h._refresh_cookie = lambda value, **_: 'refresh=' + value
    assert h._bearer_token() == 'renewed'
    assert h._oidc_response_cookies == ['access=renewed', 'refresh=rotated']


def test_valid_access_skips_refresh_and_insecure_transport_never_uses_refresh(monkeypatch):
    monkeypatch.setattr(manager_oidc, 'refresh_browser_tokens', lambda _: pytest.fail('must not refresh'))
    h = RequestSecurityMixin()
    current = token(time.time() + 300)
    h.headers = {'Cookie': 'ft-manager-session=' + current + '; tr-oidc-refresh=refresh'}
    h._has_secure_ui_transport = lambda: True
    assert h._bearer_token() == current
    h2 = RequestSecurityMixin()
    h2.headers = {'Cookie': 'tr-oidc-refresh=refresh'}
    h2._has_secure_ui_transport = lambda: False
    assert h2._bearer_token() == ''


def test_refresh_outage_retains_credentials_for_retry(monkeypatch):
    def unavailable(_): raise OSError('unavailable')
    monkeypatch.setattr(manager_oidc, 'refresh_browser_tokens', unavailable)
    h = RequestSecurityMixin()
    h.headers = {'Cookie': 'tr-oidc-refresh=refresh'}
    h._has_secure_ui_transport = lambda: True
    assert h._bearer_token() == ''
    assert h._oidc_temporarily_unavailable
    assert not hasattr(h, '_oidc_response_cookies')


def test_refresh_cookie_is_http_only_and_bounded():
    from server.manager.http.auth_routes import AuthenticationRoutesMixin
    from server.manager.config import MANAGER_SESSION_TTL_SECONDS
    h = AuthenticationRoutesMixin()
    h._is_secure_transport = lambda: True
    cookie = h._refresh_cookie('credential', max_age=MANAGER_SESSION_TTL_SECONDS * 2)
    assert f'Max-Age={MANAGER_SESSION_TTL_SECONDS}' in cookie
    assert 'HttpOnly' in cookie and 'Secure;' in cookie and 'SameSite=Lax' in cookie
    assert 'Max-Age=0' in h._refresh_cookie('')
