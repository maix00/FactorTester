"""Keycloak-managed policy for the shared public visitor identity.

The browser remains anonymous.  The Manager periodically authenticates its
dedicated, low-privilege Keycloak service account and derives the visitor
capabilities only from that account's client roles.  The browser's visitor
cookie is only a short-lived pseudonymous namespace for quotas and public
jobs; it is not an identity or permission grant.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path
import threading
import time
from urllib.parse import urlparse

from server.identity.keycloak import ServiceOIDCClient


POLICY_REFRESH_SECONDS = 10.0
FAILURE_CACHE_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class VisitorPolicy:
    subject: str
    roles: frozenset[str]

    @property
    def can_access(self) -> bool:
        return "access" in self.roles

    @property
    def can_submit(self) -> bool:
        return self.can_access and "submit" in self.roles

    @property
    def can_download_artifacts(self) -> bool:
        return self.can_access and "artifact-download" in self.roles


class KeycloakVisitorPolicyProvider:
    """Refresh one service-account policy at a bounded interval.

    Each Manager performs at most one client-credentials grant and one token
    introspection per refresh interval, rather than making Keycloak calls for
    every public request.  Role changes are observed within the configured
    refresh interval; failures deny access after the short failure cache.
    """

    def __init__(
        self,
        client: ServiceOIDCClient,
        *,
        issuer: str,
        client_id: str,
        roles_client_id: str,
        refresh_seconds: float = POLICY_REFRESH_SECONDS,
    ) -> None:
        self.client = client
        self.issuer = issuer.rstrip("/")
        self.client_id = client_id
        self.roles_client_id = roles_client_id
        self.refresh_seconds = max(1.0, float(refresh_seconds))
        self._policy: VisitorPolicy | None = None
        self._refresh_at = 0.0
        self._lock = threading.Lock()

    def policy(self) -> VisitorPolicy | None:
        now = time.monotonic()
        if now < self._refresh_at:
            return self._policy
        with self._lock:
            now = time.monotonic()
            if now < self._refresh_at:
                return self._policy
            try:
                token_response = self.client.client_credentials()
                token = str(token_response.get("access_token") or "")
                expires_in = float(token_response.get("expires_in") or 0)
                if not token or expires_in <= 0:
                    raise ValueError("Keycloak did not issue a visitor token")
                claims = self.client.introspect(token)
                policy = self._policy_from_claims(claims)
                if policy is None:
                    raise PermissionError("Keycloak visitor identity is inactive")
                refresh_after = min(self.refresh_seconds, max(1.0, expires_in - 1.0))
                self._policy = policy if policy.can_access else None
                self._refresh_at = now + refresh_after
            except Exception:
                # An unavailable or malformed identity provider must never
                # extend a previously granted visitor policy.
                self._policy = None
                self._refresh_at = now + FAILURE_CACHE_SECONDS
            return self._policy

    def _policy_from_claims(self, claims: object) -> VisitorPolicy | None:
        if not isinstance(claims, dict):
            return None
        now = time.time()
        try:
            expires = float(claims.get("exp") or 0)
        except (TypeError, ValueError):
            return None
        client_identity = str(
            claims.get("client_id") or claims.get("azp") or ""
        )
        if not (
            claims.get("active") is True
            and claims.get("iss") == self.issuer
            and expires > now
            and claims.get("sub")
            and client_identity == self.client_id
        ):
            return None
        resource_access = claims.get("resource_access")
        role_resource = (
            resource_access.get(self.roles_client_id)
            if isinstance(resource_access, dict)
            else None
        )
        raw_roles = role_resource.get("roles") if isinstance(role_resource, dict) else ()
        roles = frozenset(
            role for role in raw_roles
            if isinstance(role, str)
        ) if isinstance(raw_roles, (list, tuple)) else frozenset()
        return VisitorPolicy(str(claims["sub"]), roles)


def _environment_value(name: str, fallback: str = "") -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    if fallback:
        from server import branding

        return str(branding.env(fallback) or "").strip()
    return ""


def _visitor_settings() -> tuple[str, str, str, str, int, str, str]:
    issuer = _environment_value(
        "TR_KEYCLOAK_VISITOR_ISSUER", "USER_OIDC_ISSUER"
    ).rstrip("/")
    if not issuer:
        base = _environment_value("TRADERESEARCH_KEYCLOAK_URL", "KEYCLOAK_URL").rstrip("/")
        realm = _environment_value("TRADERESEARCH_KEYCLOAK_REALM", "KEYCLOAK_REALM").strip("/")
        if base and realm:
            issuer = f"{base}/realms/{realm}"
    client_id = _environment_value("TR_KEYCLOAK_VISITOR_CLIENT_ID")
    roles_client_id = (
        _environment_value("TR_KEYCLOAK_VISITOR_ROLES_CLIENT_ID") or client_id
    )
    secret_path = _environment_value("TR_KEYCLOAK_VISITOR_CLIENT_SECRET_FILE")
    secret = _environment_value("TR_KEYCLOAK_VISITOR_CLIENT_SECRET")
    backchannel = _environment_value("TR_KEYCLOAK_VISITOR_BACKCHANNEL_URL")
    if not backchannel:
        backchannel = _environment_value("TR_USER_OIDC_BACKCHANNEL_URL", "USER_OIDC_BACKCHANNEL_URL")
    mtime = 0
    if secret_path:
        mtime = Path(secret_path).stat().st_mtime_ns
    if not (issuer and client_id and roles_client_id and (secret_path or secret)):
        raise ValueError("Keycloak visitor client is not configured")
    base, _, realm = issuer.rpartition("/realms/")
    from server.identity.user_session import _backchannel_base_url
    backchannel = _backchannel_base_url(base, backchannel or None)
    parsed = urlparse(issuer)
    base, separator, realm = issuer.rpartition("/realms/")
    if (
        not separator or not realm or "/" in realm
        or parsed.scheme not in {"https", "http"} or not parsed.hostname
    ):
        raise ValueError("invalid Keycloak visitor issuer")
    return issuer, client_id, roles_client_id, secret_path, mtime, secret, backchannel


@lru_cache(maxsize=4)
def _provider(
    issuer: str,
    client_id: str,
    roles_client_id: str,
    secret_path: str,
    secret_mtime: int,
    secret: str,
    backchannel_base_url: str,
) -> KeycloakVisitorPolicyProvider:
    del secret_mtime
    base, _, realm = issuer.rpartition("/realms/")
    if secret_path:
        secret = Path(secret_path).read_text().strip()
    if not secret:
        raise ValueError("Keycloak visitor client secret is empty")
    return KeycloakVisitorPolicyProvider(
        ServiceOIDCClient(
            backchannel_base_url,
            realm,
            client_id,
            client_secret=secret,
            timeout=3.0,
        ),
        issuer=issuer,
        client_id=client_id,
        roles_client_id=roles_client_id,
    )


def keycloak_visitor_policy() -> VisitorPolicy | None:
    """Return the current Keycloak visitor policy, failing closed if absent."""
    try:
        return _provider(*_visitor_settings()).policy()
    except (KeyError, OSError, TypeError, ValueError):
        return None
