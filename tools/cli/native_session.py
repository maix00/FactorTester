"""Endpoint-scoped session handed off by the authenticated native client."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit


def session_path(endpoint: str) -> Path:
    from tools.cli.http import _home_dir
    digest = hashlib.sha256(endpoint.rstrip('/').encode()).hexdigest()
    return _home_dir() / 'native-sessions' / (digest + '.json')


def load_token(endpoint: str) -> str:
    value = _read(endpoint)
    if value.get('oauth') and time.time() >= value['oauth']['expires_at'] - 30:
        with _credential_lock(endpoint):
            value = _read(endpoint)
            if value.get('oauth') and time.time() >= value['oauth']['expires_at'] - 30:
                from tools.cli.oidc_device import refresh_session
                value = refresh_session(endpoint, value)
                _write(endpoint, value)
    return str(value.get('token') or '')


def _read(endpoint: str) -> dict:
    try:
        value = json.loads(session_path(endpoint).read_text())
    except FileNotFoundError:
        return {}
    if value.get('endpoint') != endpoint.rstrip('/'):
        raise ValueError('native session endpoint does not match')
    return value


def save_session(endpoint: str, principal: str, token: str, certificate_pem: str = "") -> None:
    parsed = urlsplit(endpoint)
    if (parsed.scheme not in {'http', 'https'} or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError('native session endpoint is invalid')
    with _credential_lock(endpoint):
        _write(endpoint, {'endpoint': endpoint.rstrip('/'), 'principal': principal,
                         'token': token, 'certificate_pem': certificate_pem})


@contextmanager
def _credential_lock(endpoint: str):
    """Serialize refresh-token rotation and native handoff across CLI processes."""
    target = session_path(endpoint).with_suffix('.lock')
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(target, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, 'r+b') as handle:
        if os.name == 'nt':
            import msvcrt
            if not target.stat().st_size:
                handle.write(b'\0')
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == 'nt':
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _write(endpoint: str, value: dict) -> None:
    target = session_path(endpoint)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=target.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def clear_session(endpoint: str) -> None:
    with _credential_lock(endpoint):
        session_path(endpoint).unlink(missing_ok=True)


def save_device_session(endpoint: str, current: dict, tokens: dict, config: dict) -> None:
    with _credential_lock(endpoint):
        previous = _read(endpoint)
        _write(endpoint, {
            'endpoint': endpoint.rstrip('/'), 'principal': current['username'],
            'token': tokens['access_token'],
            'certificate_pem': previous.get('certificate_pem', ''),
            'oauth': {**config, 'subject': current['keycloak_subject'],
                      'refresh_token': tokens['refresh_token'],
                      'token_endpoint': tokens['token_endpoint'],
                      'expires_at': time.time() + tokens['expires_in']},
        })


def certificate_for(endpoint: str) -> str:
    try:
        value = json.loads(session_path(endpoint).read_text())
    except FileNotFoundError:
        return ''
    return str(value.get('certificate_pem') or '') if value.get('endpoint') == endpoint.rstrip('/') else ''


def transfer_tls_context(url: str, authority: str = ''):
    """Share only certificate trust with server-declared data endpoints, never credentials."""
    import ssl
    target = urlsplit(url)
    if target.scheme != 'https':
        return None
    origin = f'{target.scheme}://{target.netloc}'
    pem = certificate_for(origin)
    if not pem and authority:
        source = urlsplit(authority)
        if source.scheme == 'https' and source.hostname == target.hostname:
            pem = certificate_for(authority)
    if not pem:
        return None
    context = ssl.create_default_context()
    context.load_verify_locations(cadata=pem)
    return context
