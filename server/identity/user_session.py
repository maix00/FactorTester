"""Manager bearer sessions verified by Keycloak's token introspection endpoint."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import threading
import time

from server.identity.keycloak import ServiceOIDCClient
from server.identity.realm_groups import (
    administrative_group_role,
    normalize_group_claim,
)


PUBLIC_SERVER_LOGIN_ROLE = "public_server:login"


def may_login_public_server(session: object) -> bool:
    """Return whether a verified Keycloak session may enter the public Manager."""
    if not isinstance(session, dict):
        return False
    roles = session.get("keycloak_roles", ())
    return isinstance(roles, (tuple, list, set, frozenset)) and (
        PUBLIC_SERVER_LOGIN_ROLE in roles
    )


class UserSessionVerifier:
    def __init__(self, client, *, issuer: str, audience: str,
                 roles_client_id: str | None = None):
        self.client, self.issuer, self.audience = client, issuer.rstrip('/'), audience
        self.roles_client_id = str(roles_client_id or audience)
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
        try:
            claims = self.client.introspect(token)
        except Exception:
            return None
        if not isinstance(claims, dict):
            return None
        audience = claims.get('aud', [])
        if isinstance(audience, str):
            audience = [audience]
        expires = float(claims.get('exp') or 0)
        authorized_party = str(claims.get("azp") or "")
        if (claims.get('active') is not True or claims.get('iss') != self.issuer
                or (self.audience not in audience and authorized_party != self.audience)
                or expires <= now
                or not claims.get('sub') or not claims.get('preferred_username')):
            return None
        access = claims.get('resource_access', {})
        client_access = access.get(self.roles_client_id, {}) if isinstance(access, dict) else {}
        roles = client_access.get('roles', []) if isinstance(client_access, dict) else []
        roles = tuple(sorted({r for r in roles if isinstance(r, str)})) if isinstance(roles, list) else ()
        groups = normalize_group_claim(claims.get("groups"))
        if groups is None:
            return None
        role = (
            "super_admin" if "admin_console:manage" in roles
            else administrative_group_role(groups)
        )
        admin_capabilities = [
            r for r in roles
            if r in {"admin_console:read", "admin_console:manage"}
        ]
        if role in {"org_admin", "level_admin"}:
            admin_capabilities.append("identity:manage")
        if role == "org_admin":
            # The organization administrator role is projected from an exact
            # Keycloak Realm Group claim. Server routes still constrain every
            # operation to the matching organization group path.
            admin_capabilities.append("federation:manage")
        value = {
            # The admin-owned label preserves existing object owner refs;
            # Keycloak normalizes its login name to lowercase. Never accept
            # this mapping without the stable migrated identity claim.
            'username': (_string_claim(claims, 'tr_username')
                         if _string_claim(claims, 'tr_identity_id')
                         and _string_claim(claims, 'tr_username')
                         else str(claims['preferred_username'])),
            'alias': str(claims.get('name') or claims['preferred_username']),
            'role': role,
            'keycloak_subject': str(claims['sub']),
            'keycloak_issuer': self.issuer,
            'tr_identity_id': _string_claim(claims, 'tr_identity_id'),
            'organization_id': _string_claim(claims, 'tr_organization_id'),
            'organization_name': _string_claim(claims, 'tr_organization_name'),
            'level_id': _string_claim(claims, 'tr_level_id'),
            'parent_identity_id': _string_claim(claims, 'tr_parent_identity_id'),
            'parent_username': _string_claim(claims, 'tr_parent_username'),
            'keycloak_groups': groups,
            'keycloak_roles': roles,
            'public_server_login': PUBLIC_SERVER_LOGIN_ROLE in roles,
            'expires_in': max(0, int(expires - now)),
            'admin_capabilities': admin_capabilities,
            'capabilities': {
                'manager': 'admin_console:manage' in roles,
                'research': True,
            },
        }
        with self._lock:
            if len(self._cache) >= 256:
                self._cache.clear()
            self._cache[key] = (min(expires, now + 5), value)
        return dict(value)


def _string_claim(claims: dict, key: str) -> str:
    value = claims.get(key)
    if value is None:
        return ''
    if not isinstance(value, str) or len(value) > 512:
        raise ValueError(f"invalid Keycloak {key} claim")
    return value.strip()


@lru_cache(maxsize=4)
def _configured(issuer, audience, roles_client_id, client_id,
                backchannel_base_url, secret_path, mtime):
    del mtime
    base, separator, realm = issuer.rpartition('/realms/')
    if not separator or not realm or '/' in realm:
        raise ValueError('invalid Keycloak issuer')
    secret = Path(secret_path).read_text().strip()
    if not secret:
        raise ValueError('missing Keycloak introspection credential')
    return UserSessionVerifier(
        ServiceOIDCClient(backchannel_base_url, realm, client_id, client_secret=secret),
        issuer=issuer, audience=audience, roles_client_id=roles_client_id,
    )


@lru_cache(maxsize=4)
def _configured_secret(issuer, audience, roles_client_id, client_id,
                       backchannel_base_url, secret):
    base, separator, realm = issuer.rpartition('/realms/')
    if not separator or not realm or '/' in realm:
        raise ValueError('invalid Keycloak issuer')
    return UserSessionVerifier(
        ServiceOIDCClient(backchannel_base_url, realm, client_id, client_secret=secret),
        issuer=issuer, audience=audience, roles_client_id=roles_client_id,
    )


def _backchannel_base_url(
    public_base_url: str, configured_override: str | None = None,
) -> str:
    """Resolve the private Keycloak endpoint used for server-to-server calls.

    Browser redirects and token issuers must use the canonical public URL.
    Manager containers may reach the same Keycloak over their private Docker
    network to avoid a public-IP hairpin and duplicate internet traffic.
    Plain HTTP is accepted only for a single-label/private-network hostname or
    a private/loopback IP; public issuer URLs remain HTTPS in production.
    """
    import ipaddress
    import os
    from urllib.parse import urlsplit, urlunsplit

    configured = str(configured_override or "").strip()
    if not configured and configured_override is None:
        configured = str(os.environ.get("TR_USER_OIDC_BACKCHANNEL_URL") or "").strip()
    if not configured and configured_override is None:
        from server import branding

        configured = str(branding.env("USER_OIDC_BACKCHANNEL_URL") or "").strip()
    if not configured:
        return str(public_base_url).rstrip("/")
    parsed = urlsplit(configured)
    public_path = urlsplit(str(public_base_url)).path.rstrip("/")
    configured_path = parsed.path.rstrip("/")
    if (parsed.scheme not in {"https", "http"} or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or configured_path != public_path
            or ".." in configured_path.split("/")
            or "\\" in configured_path):
        raise ValueError("invalid Keycloak backchannel URL")
    if parsed.scheme == "http":
        host = parsed.hostname.lower()
        try:
            address = ipaddress.ip_address(host)
            private_host = address.is_private or address.is_loopback or address.is_link_local
        except ValueError:
            private_host = "." not in host or host.endswith((".internal", ".local"))
        if not private_host:
            raise ValueError("plain HTTP Keycloak backchannel must use a private endpoint")
    return urlunsplit((parsed.scheme, parsed.netloc, configured_path, "", "")).rstrip("/")


def oidc_settings() -> dict[str, str]:
    """Resolve the shared Manager OIDC client settings without exposing secrets."""
    import os
    from server import branding

    issuer = (os.environ.get("TR_USER_OIDC_ISSUER")
              or branding.env("USER_OIDC_ISSUER")).strip().rstrip("/")
    if not issuer:
        base = branding.env("KEYCLOAK_URL").strip().rstrip("/")
        realm = branding.env("KEYCLOAK_REALM").strip("/")
        if base and realm:
            issuer = f"{base}/realms/{realm}"
    client_id = (os.environ.get("TR_USER_OIDC_CLIENT_ID")
                 or branding.env("USER_OIDC_CLIENT_ID")
                 or branding.env("KEYCLOAK_CLIENT_ID")).strip()
    audience = (os.environ.get("TR_USER_OIDC_AUDIENCE")
                or branding.env("USER_OIDC_AUDIENCE")
                or client_id).strip()
    roles_client_id = (
        os.environ.get("TR_USER_OIDC_ROLES_CLIENT_ID")
        or branding.env("USER_OIDC_ROLES_CLIENT_ID")
        or client_id
    ).strip()
    secret_path = (os.environ.get("TR_USER_OIDC_CLIENT_SECRET_FILE")
                   or branding.env("USER_OIDC_CLIENT_SECRET_FILE")).strip()
    secret = ""
    if secret_path:
        secret = Path(secret_path).read_text().strip()
    else:
        secret = (os.environ.get("TR_USER_OIDC_CLIENT_SECRET")
                  or branding.env("USER_OIDC_CLIENT_SECRET")
                  or branding.env("KEYCLOAK_CLIENT_SECRET")).strip()
    base, separator, realm = issuer.rpartition("/realms/")
    if not (separator and base.startswith(("https://", "http://")) and realm
            and "/" not in realm and client_id and audience and roles_client_id):
        raise ValueError("Keycloak OIDC client is not configured")
    if not secret:
        raise ValueError("Keycloak introspection credential is not configured")
    authz_client_id = (
        os.environ.get("TR_KEYCLOAK_AUTHZ_CLIENT_ID")
        or branding.env("KEYCLOAK_AUTHZ_CLIENT_ID")
        or client_id
    ).strip()
    authz_secret_path = (
        os.environ.get("TR_KEYCLOAK_AUTHZ_CLIENT_SECRET_FILE")
        or branding.env("KEYCLOAK_AUTHZ_CLIENT_SECRET_FILE")
    ).strip()
    authz_client_secret = (
        Path(authz_secret_path).read_text().strip()
        if authz_secret_path else (
            os.environ.get("TR_KEYCLOAK_AUTHZ_CLIENT_SECRET")
            or branding.env("KEYCLOAK_AUTHZ_CLIENT_SECRET")
            or secret
        ).strip()
    )
    backchannel_base_url = _backchannel_base_url(base)
    return {
        "issuer": issuer, "audience": audience, "roles_client_id": roles_client_id,
        "client_id": client_id, "backchannel_base_url": backchannel_base_url,
        "client_secret": secret, "base_url": base, "realm": realm,
        "secret_path": secret_path,
        "authz_client_id": authz_client_id,
        "authz_client_secret": authz_client_secret,
    }


def keycloak_session(token: str):
    import os
    try:
        settings = oidc_settings()
        secret_path = Path(settings["secret_path"]) if settings["secret_path"] else None
        if secret_path is not None:
            verifier = _configured(
                settings["issuer"], settings["audience"], settings["roles_client_id"],
                settings["client_id"], settings["backchannel_base_url"],
                str(secret_path), secret_path.stat().st_mtime_ns,
            )
        else:
            verifier = _configured_secret(
                settings["issuer"], settings["audience"], settings["roles_client_id"],
                settings["client_id"],
                settings["backchannel_base_url"],
                settings["client_secret"],
            )
        return verifier.session(token)
    except (KeyError, OSError, ValueError, TypeError):
        return None
