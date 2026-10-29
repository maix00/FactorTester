"""Manager bearer sessions verified by Keycloak's token introspection endpoint."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import threading
import time

from server.identity.keycloak import ServiceOIDCClient


class UserSessionVerifier:
    def __init__(self, client, *, issuer: str, audience: str):
        self.client, self.issuer, self.audience = client, issuer.rstrip('/'), audience
        self._cache = {}
        self._lock = threading.Lock()

    def session(self, token: str):
        import hashlib
        if not token or len(token) > 32768:
            return None
        key = hashlib.sha256(token.encode()).digest()
        now = time.time()
        with self._lock:
            cached = self._cache.get(key)
            if cached and cached[0] > now:
                return dict(cached[1])
        claims = self.client.introspect(token)
        if not isinstance(claims, dict):
            return None
        audience = claims.get('aud', [])
        if isinstance(audience, str):
            audience = [audience]
        expires = float(claims.get('exp') or 0)
        if (claims.get('active') is not True or claims.get('iss') != self.issuer
                or self.audience not in audience or expires <= now
                or not claims.get('sub') or not claims.get('preferred_username')):
            return None
        access = claims.get('resource_access', {})
        client_access = access.get(self.audience, {}) if isinstance(access, dict) else {}
        roles = client_access.get('roles', []) if isinstance(client_access, dict) else []
        roles = tuple(sorted({r for r in roles if isinstance(r, str)})) if isinstance(roles, list) else ()
        value = {
            'username': str(claims['preferred_username']),
            'alias': str(claims.get('name') or claims['preferred_username']),
            'role': 'user',
            'keycloak_subject': str(claims['sub']),
            'keycloak_roles': roles,
            'admin_capabilities': [r for r in roles if r in {'admin_console:read', 'admin_console:manage'}],
            'capabilities': {'manager': 'admin_console:manage' in roles, 'research': True},
        }
        with self._lock:
            if len(self._cache) >= 256:
                self._cache.clear()
            self._cache[key] = (min(expires, now + 5), value)
        return dict(value)


@lru_cache(maxsize=4)
def _configured(issuer, audience, client_id, secret_path, mtime):
    del mtime
    base, separator, realm = issuer.rpartition('/realms/')
    if not separator or not realm or '/' in realm:
        raise ValueError('invalid Keycloak issuer')
    secret = Path(secret_path).read_text().strip()
    if not secret:
        raise ValueError('missing Keycloak introspection credential')
    return UserSessionVerifier(ServiceOIDCClient(base, realm, client_id, client_secret=secret),
                               issuer=issuer, audience=audience)


def keycloak_session(token: str):
    import os
    try:
        path = Path(os.environ['TR_USER_OIDC_CLIENT_SECRET_FILE'])
        return _configured(os.environ['TR_USER_OIDC_ISSUER'].rstrip('/'),
                           os.environ['TR_USER_OIDC_AUDIENCE'],
                           os.environ['TR_USER_OIDC_CLIENT_ID'], str(path),
                           path.stat().st_mtime_ns).session(token)
    except (KeyError, OSError, ValueError, TypeError):
        return None
