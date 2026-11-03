import json
import stat

import pytest

from tools.cli import native_session, oidc_device


ISSUER = 'https://identity.example/realms/research'
ENDPOINT = 'https://manager.example'
DOCUMENT = {'issuer': ISSUER, **{key: ISSUER + '/protocol/openid-connect/' + path for key, path in (
    ('device_authorization_endpoint', 'auth/device'), ('token_endpoint', 'token'),
    ('revocation_endpoint', 'revoke'))}}


def protocol(results):
    calls = []
    def request(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith('device-configuration'):
            return {'issuer': ISSUER, 'client_id': 'traderesearch-cli'}
        if url.endswith('openid-configuration'):
            return DOCUMENT
        if url.endswith('auth/device'):
            return {'device_code': 'secret-device', 'user_code': 'VISIBLE', 'expires_in': 30,
                    'interval': 2, 'verification_uri': ISSUER + '/device'}
        return next(results)
    return request, calls


def test_device_poll_obeys_pending_and_slow_down_without_exposing_tokens():
    request, calls = protocol(iter([{'error': 'authorization_pending'}, {'error': 'slow_down'},
                                   {'access_token': 'access', 'refresh_token': 'refresh', 'expires_in': 60}]))
    now, sleeps, shown = [0], [], []
    def sleep(n):
        sleeps.append(n)
        now[0] += n
    config, tokens = oidc_device.authorize(ENDPOINT, request=request, clock=lambda: now[0],
        sleep=sleep, open_browser=False, show=lambda *v: shown.append(v))
    assert sleeps == [2, 2, 7]
    assert shown == [(ISSUER + '/device', 'VISIBLE')]
    assert tokens['access_token'] == 'access'
    assert config['revocation_endpoint'] == DOCUMENT['revocation_endpoint']
    assert all(call[1]['authority'] == ENDPOINT for call in calls)


@pytest.mark.parametrize('error', ['access_denied', 'expired_token', 'invalid_client'])
def test_denied_authorization_has_no_credential_persistence(error):
    request, _ = protocol(iter([{'error': error}]))
    with pytest.raises(oidc_device.DeviceLoginError, match='denied or expired'):
        oidc_device.authorize(ENDPOINT, request=request, clock=lambda: 0, sleep=lambda n: None,
                              open_browser=False, show=lambda *v: None)


@pytest.mark.parametrize('url', ['https://evil.example/token', ISSUER + '/../elsewhere',
    'https://user:password@identity.example/realms/research/token', 'http://example.com/token'])
def test_untrusted_identity_endpoints_rejected(url):
    with pytest.raises(oidc_device.DeviceLoginError):
        oidc_device._url(url, issuer=ISSUER)


def test_device_credentials_refresh_rotate_once_and_preserve_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(native_session, 'session_path', lambda e: tmp_path / ('one.json' if e == ENDPOINT else 'two.json'))
    current = {'username': 'stable-user', 'keycloak_subject': 'subject', 'keycloak_issuer': ISSUER}
    native_session.save_device_session(ENDPOINT, current,
        {'access_token': 'access', 'refresh_token': 'refresh', 'expires_in': 60, 'token_endpoint': DOCUMENT['token_endpoint']},
        {'issuer': ISSUER, 'client_id': 'traderesearch-cli', 'revocation_endpoint': DOCUMENT['revocation_endpoint']})
    path = native_session.session_path(ENDPOINT)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    old = json.loads(path.read_text())
    old['oauth']['expires_at'] = 0
    path.write_text(json.dumps(old))
    calls = []
    monkeypatch.setattr(oidc_device, 'request_json', lambda *a, **kw: calls.append(kw) or {
        'access_token': 'rotated', 'refresh_token': 'rotated-refresh', 'expires_in': 60})
    monkeypatch.setattr('tools.cli.http.HttpSession.get', lambda self, path: current)
    assert native_session.load_token(ENDPOINT) == 'rotated'
    assert native_session.load_token(ENDPOINT) == 'rotated'
    assert len(calls) == 1
    assert json.loads(path.read_text())['oauth']['refresh_token'] == 'rotated-refresh'
    assert native_session.load_token('https://other.example') == ''


def test_refresh_does_not_accept_different_subject(monkeypatch):
    monkeypatch.setattr(oidc_device, 'request_json', lambda *a, **kw: {'access_token': 'new', 'expires_in': 60})
    monkeypatch.setattr('tools.cli.http.HttpSession.get', lambda self, path: {
        'username': 'same', 'keycloak_subject': 'different', 'keycloak_issuer': ISSUER})
    with pytest.raises(oidc_device.DeviceLoginError, match='identity changed'):
        oidc_device.refresh_session(ENDPOINT, {'principal': 'same', 'oauth': {
            'subject': 'original', 'issuer': ISSUER, 'token_endpoint': DOCUMENT['token_endpoint'],
            'client_id': 'cli', 'refresh_token': 'secret'}})
