"""Keycloak RFC 8628 device login; credentials stay with the endpoint's client.

This is a protocol adapter, not an identity/permission authority. Manager must
validate the issued access token before anything is persisted. No password,
client secret or browser cookie is accepted by this flow.
"""
from __future__ import annotations

import json
import time
import webbrowser
from urllib.error import HTTPError
from urllib.parse import unquote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

LIMIT = 128 * 1024


class DeviceLoginError(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _url(value: str, *, issuer: str = '') -> str:
    import ipaddress
    if not isinstance(value, str) or any(ord(c) < 33 or ord(c) == 127 for c in value):
        raise DeviceLoginError('invalid identity endpoint')
    parsed = urlsplit(value)
    if any(part in {'.', '..'} for part in unquote(parsed.path).split('/')):
        raise DeviceLoginError('invalid identity endpoint')
    if (parsed.scheme not in {'https', 'http'} or not parsed.hostname or parsed.username
            or parsed.password or parsed.fragment):
        raise DeviceLoginError('invalid identity endpoint')
    if parsed.scheme == 'http':
        try:
            private = ipaddress.ip_address(parsed.hostname).is_private
        except ValueError:
            private = parsed.hostname == 'localhost'
        if not private:
            raise DeviceLoginError('identity endpoint requires HTTPS')
    if issuer:
        expected = urlsplit(issuer)
        if (parsed.scheme, parsed.netloc) != (expected.scheme, expected.netloc) or not parsed.path.startswith(expected.path.rstrip('/') + '/'):
            raise DeviceLoginError('identity endpoint differs from the trusted issuer')
    return value


def request_json(url: str, *, authority: str, form: dict | None = None, empty_ok: bool = False) -> dict:
    from tools.cli.native_session import transfer_tls_context
    context = transfer_tls_context(url, authority)
    opener = build_opener(NoRedirect(), *([HTTPSHandler(context=context)] if context else []))
    request = Request(url, data=None if form is None else urlencode(form).encode(),
                      headers={'Accept': 'application/json', 'Content-Type': 'application/x-www-form-urlencoded'})
    try:
        response = opener.open(request, timeout=15)
    except HTTPError as exc:
        if exc.code not in {400, 401, 403}:
            raise DeviceLoginError(f'identity request failed (HTTP {exc.code})') from None
        response = exc
    with response:
        raw = response.read(LIMIT + 1)
        if not raw and empty_ok and response.status in {200, 204}:
            return {}
        if len(raw) > LIMIT:
            raise DeviceLoginError('identity response exceeds the limit')
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            raise DeviceLoginError('identity endpoint returned invalid JSON') from None
        if not isinstance(value, dict):
            raise DeviceLoginError('identity endpoint returned invalid JSON')
        return value


def discover(endpoint: str, *, request=request_json) -> tuple[dict, dict]:
    config = request(endpoint.rstrip('/') + '/auth/oidc/device-configuration', authority=endpoint)
    issuer = _url(config.get('issuer', '')).rstrip('/')
    if urlsplit(issuer).query:
        raise DeviceLoginError('invalid identity issuer')
    client = config.get('client_id')
    if not isinstance(client, str) or not client or len(client) > 255:
        raise DeviceLoginError('Manager has no CLI login client')
    document = request(issuer + '/.well-known/openid-configuration', authority=endpoint)
    if document.get('issuer') != issuer:
        raise DeviceLoginError('identity discovery issuer mismatch')
    for key in ('device_authorization_endpoint', 'token_endpoint', 'revocation_endpoint'):
        _url(document.get(key, ''), issuer=issuer)
    return {'issuer': issuer, 'client_id': client}, document


def authorize(endpoint: str, *, show, open_browser: bool = True,
              request=request_json, clock=time.monotonic, sleep=time.sleep) -> tuple[dict, dict]:
    config, discovery = discover(endpoint, request=request)
    issued = request(discovery['device_authorization_endpoint'], authority=endpoint,
                     form={'client_id': config['client_id'], 'scope': 'openid profile'})
    device = issued.get('device_code')
    expires, interval = issued.get('expires_in'), issued.get('interval', 5)
    if (not isinstance(device, str) or not device or len(device) > 8192
            or type(expires) is not int or not 1 <= expires <= 1800
            or type(interval) is not int or not 1 <= interval <= 60):
        raise DeviceLoginError('Keycloak did not issue a bounded device login')
    verification = _url(issued.get('verification_uri_complete') or issued.get('verification_uri', ''), issuer=config['issuer'])
    code = issued.get('user_code')
    if not isinstance(code, str) or not code or len(code) > 128:
        raise DeviceLoginError('Keycloak did not issue a verification code')
    show(verification, code)
    if open_browser:
        webbrowser.open(verification)
    deadline = clock() + expires
    while clock() < deadline:
        sleep(min(interval, max(0, deadline - clock())))
        if clock() >= deadline:
            break
        result = request(discovery['token_endpoint'], authority=endpoint, form={
            'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
            'device_code': device, 'client_id': config['client_id'],
        })
        error = result.get('error')
        if error == 'authorization_pending':
            continue
        if error == 'slow_down':
            interval = min(interval + 5, 60)
            continue
        if error:
            raise DeviceLoginError('Keycloak device login was denied or expired')
        token, refresh, lifetime = result.get('access_token'), result.get('refresh_token'), result.get('expires_in')
        if (not isinstance(token, str) or not token or len(token) > 32768
                or not isinstance(refresh, str) or not refresh or len(refresh) > 32768
                or type(lifetime) is not int or not 1 <= lifetime <= 86400):
            raise DeviceLoginError('Keycloak returned incomplete user credentials')
        return {**config, 'revocation_endpoint': discovery['revocation_endpoint']}, {**result, 'token_endpoint': discovery['token_endpoint']}
    raise DeviceLoginError('Keycloak device login expired')


def login(endpoint: str, *, show, open_browser: bool = True) -> dict:
    from tools.cli.http import HttpSession
    from tools.cli.native_session import save_device_session
    config, tokens = authorize(endpoint, show=show, open_browser=open_browser)
    current = HttpSession(endpoint, bearer_token=tokens['access_token'], persist_cookies=False).get('/api/session')
    if (not isinstance(current, dict) or not current.get('username') or current.get('visitor_login')
            or current.get('authentication') == 'agent' or current.get('keycloak_issuer', '').rstrip('/') != config['issuer']):
        raise DeviceLoginError('Manager did not authorize this Keycloak user')
    if not current.get('keycloak_subject'):
        raise DeviceLoginError('Manager did not return a verified Keycloak subject')
    save_device_session(endpoint, current, tokens, config)
    return current


def refresh_session(endpoint: str, saved: dict) -> dict:
    from tools.cli.http import HttpSession
    oauth = saved['oauth']
    url = _url(oauth['token_endpoint'], issuer=oauth['issuer'])
    result = request_json(url, authority=endpoint, form={
        'grant_type': 'refresh_token', 'client_id': oauth['client_id'],
        'refresh_token': oauth['refresh_token'],
    })
    token, lifetime = result.get('access_token'), result.get('expires_in')
    if (result.get('error') or not isinstance(token, str) or not token or len(token) > 32768
            or type(lifetime) is not int or not 1 <= lifetime <= 86400):
        raise DeviceLoginError('Keycloak session expired; run traderesearch login')
    current = HttpSession(endpoint, bearer_token=token, persist_cookies=False).get('/api/session')
    if (current.get('keycloak_subject') != oauth['subject']
            or current.get('keycloak_issuer', '').rstrip('/') != oauth['issuer']
            or current.get('username') != saved['principal'] or current.get('visitor_login')
            or current.get('authentication') == 'agent'):
        raise DeviceLoginError('Manager identity changed during session refresh')
    refresh = result.get('refresh_token', oauth['refresh_token'])
    if not isinstance(refresh, str) or not refresh or len(refresh) > 32768:
        raise DeviceLoginError('Keycloak returned an invalid refresh credential')
    return {**saved, 'token': token, 'oauth': {**oauth, 'refresh_token': refresh,
                                            'expires_at': time.time() + lifetime}}


def revoke(endpoint: str) -> None:
    from tools.cli.native_session import _read, _credential_lock, session_path
    with _credential_lock(endpoint):
        saved = _read(endpoint)
        oauth = saved.get('oauth')
        try:
            if oauth:
                url = _url(oauth['revocation_endpoint'], issuer=oauth['issuer'])
                result = request_json(url, authority=endpoint, empty_ok=True, form={
                    'client_id': oauth['client_id'], 'token': oauth['refresh_token'],
                    'token_type_hint': 'refresh_token',
                })
                if result.get('error'):
                    raise DeviceLoginError('Keycloak did not revoke this CLI session')
        finally:
            session_path(endpoint).unlink(missing_ok=True)
