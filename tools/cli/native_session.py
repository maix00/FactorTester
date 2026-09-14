"""Endpoint-scoped session handed off by the authenticated native client."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit


def session_path(endpoint: str) -> Path:
    from tools.cli.http import _home_dir
    digest = hashlib.sha256(endpoint.rstrip('/').encode()).hexdigest()
    return _home_dir() / 'native-sessions' / (digest + '.json')


def load_token(endpoint: str) -> str:
    try:
        value = json.loads(session_path(endpoint).read_text())
    except FileNotFoundError:
        return ''
    if value.get('endpoint') != endpoint.rstrip('/'):
        raise ValueError('native session endpoint does not match')
    return str(value.get('token') or '')


def save_session(endpoint: str, principal: str, token: str, certificate_pem: str = "") -> None:
    parsed = urlsplit(endpoint)
    if (parsed.scheme not in {'http', 'https'} or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError('native session endpoint is invalid')
    target = session_path(endpoint)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=target.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump({'endpoint': endpoint.rstrip('/'), 'principal': principal, 'token': token, 'certificate_pem': certificate_pem}, stream)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def clear_session(endpoint: str) -> None:
    session_path(endpoint).unlink(missing_ok=True)


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
