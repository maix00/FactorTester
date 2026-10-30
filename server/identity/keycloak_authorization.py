"""Bounded Keycloak Authorization Services decisions for Manager resources."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import hashlib
import json
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request

from server.identity.keycloak import ServiceOIDCClient
from server.identity.user_session import oidc_settings


_CACHE_TTL_SECONDS = 2.0
_CACHE_LIMIT = 2048
_CACHE_LOCK = threading.Lock()
_CACHE: OrderedDict[tuple[bytes, str, str, str], tuple[float, bool]] = OrderedDict()
_RESOURCE_SCOPES = ("read", "write", "manage", "publish", "delete", "share", "use")


class AuthorizationUnavailable(RuntimeError):
    """Keycloak could not be reached or the resource client is misconfigured."""


@dataclass(frozen=True)
class VerifiedRequestIdentity:
    """Identity claims already verified for the current Manager request."""

    token: str = field(repr=False, compare=False)
    issuer: str
    subject: str
    username: str


def _backchannel(settings: dict[str, str]) -> str:
    return str(settings.get("backchannel_base_url") or settings["base_url"])


def keycloak_authorized(
    token: str, *, resource_id: str, scope: str,
) -> bool:
    """Evaluate one resource scope using the caller's own Keycloak token.

    There is no owner or local-role bypass here.  Resources must be registered
    in the Manager resource server and their IDs stored with the object.  A
    missing ID or denied Keycloak decision fails closed.
    """
    resource = str(resource_id or "").strip()
    permission = str(scope or "").strip()
    if not token or not resource or not permission:
        return False
    settings = oidc_settings()
    digest = hashlib.sha256(token.encode("utf-8")).digest()
    key = (digest, settings["authz_client_id"], resource, permission)
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is not None and cached[0] > now:
            _CACHE.move_to_end(key)
            return cached[1]
        if cached is not None:
            _CACHE.pop(key, None)
    client = ServiceOIDCClient(
        _backchannel(settings), settings["realm"], settings["authz_client_id"],
        client_secret=settings["authz_client_secret"], timeout=2.0,
    )
    try:
        allowed = client.authorize(
            token, audience=settings["authz_client_id"],
            resource_id=resource, scope=permission, timeout=2.0,
        )
    except Exception as exc:
        raise AuthorizationUnavailable("Keycloak authorization is unavailable") from exc
    with _CACHE_LOCK:
        while len(_CACHE) >= _CACHE_LIMIT:
            _CACHE.popitem(last=False)
        _CACHE[key] = (time.monotonic() + _CACHE_TTL_SECONDS, bool(allowed))
    return bool(allowed)


def keycloak_authorized_many(
    token: str,
    *,
    permissions: list[tuple[str, str, str]],
) -> dict[tuple[str, str], bool]:
    """Batch-check ``(resource URI, resource name, scope)`` with Keycloak.

    Results are cached per caller token and resource scope for a short bounded
    interval. Missing resources/scopes are explicit denials; a Keycloak outage
    raises so callers can distinguish unavailable authorization from denial.
    """
    if not token:
        return {(str(uri), str(scope)): False for uri, _name, scope in permissions}
    settings = oidc_settings()
    client_id = settings["authz_client_id"]
    token_digest = hashlib.sha256(token.encode("utf-8")).digest()
    now = time.monotonic()
    normalized: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for uri, name, scope in permissions:
        uri, name, scope = str(uri or "").strip(), str(name or "").strip(), str(scope or "").strip()
        if not uri or not name or not scope:
            raise ValueError("Keycloak authorization permission is incomplete")
        if not uri.startswith("/traderesearch/resources/"):
            raise ValueError("Keycloak resource URI is outside the TradeResearch namespace")
        if (uri, scope) not in seen:
            normalized.append((uri, name, scope))
            seen.add((uri, scope))
    if len(normalized) > 256:
        raise ValueError("Keycloak authorization request exceeds 256 permissions")

    result: dict[tuple[str, str], bool] = {}
    missing: list[tuple[str, str, str]] = []
    with _CACHE_LOCK:
        for uri, name, scope in normalized:
            key = (token_digest, client_id, uri, scope)
            cached = _CACHE.get(key)
            if cached is not None and cached[0] > now:
                _CACHE.move_to_end(key)
                result[(uri, scope)] = cached[1]
            else:
                if cached is not None:
                    _CACHE.pop(key, None)
                missing.append((uri, name, scope))
    if missing:
        client = ServiceOIDCClient(
            _backchannel(settings), settings["realm"], client_id,
            client_secret=settings["authz_client_secret"], timeout=2.0,
        )
        try:
            granted = client.authorize_many(
                token, audience=client_id, permissions=missing,
                resource_format="uri", timeout=2.0,
            )
        except Exception as exc:
            raise AuthorizationUnavailable("Keycloak authorization is unavailable") from exc
        missing_results = {
            (uri, scope): (uri, scope) in granted
            for uri, _name, scope in missing
        }
        with _CACHE_LOCK:
            while len(_CACHE) + len(missing_results) > _CACHE_LIMIT:
                _CACHE.popitem(last=False)
            expires = time.monotonic() + _CACHE_TTL_SECONDS
            for (uri, scope), allowed in missing_results.items():
                _CACHE[(token_digest, client_id, uri, scope)] = (expires, allowed)
                result[(uri, scope)] = allowed
    return result


def clear_authorization_cache() -> None:
    """Test and explicit revocation hook; no persistent decision state."""
    with _CACHE_LOCK:
        _CACHE.clear()


def keycloak_resource_name(resource_type: str, resource_ref: str) -> str:
    """Return a stable opaque Keycloak resource name without exposing the ref."""
    kind = "".join(ch for ch in str(resource_type).lower() if ch.isalnum() or ch in "-_" )[:48]
    ref = str(resource_ref or "").strip()
    if not kind or not ref:
        raise ValueError("resource type and reference are required")
    digest = hashlib.sha256(ref.encode("utf-8")).hexdigest()
    return f"tr:{kind}:{digest}"


def keycloak_resource_uri(resource_type: str, resource_ref: str) -> str:
    """Stable Keycloak URI identifier shared across Manager deployments."""
    name = keycloak_resource_name(resource_type, resource_ref)
    _prefix, kind, digest = name.split(":", 2)
    return f"/traderesearch/resources/{kind}/{digest}"


def keycloak_factor_source_permission(
    token: str, *, owner_username: str, factor_id: str, scope: str = "read",
) -> bool:
    """Authorize one private factor source by its stable cross-Manager ref."""
    owner = str(owner_username or "").strip()
    factor = str(factor_id or "").strip()
    if not owner or not factor:
        return False
    return keycloak_resource_permission(
        token, resource_type="factor_source",
        resource_ref=f"custom:{owner}:{factor}", scope=scope,
    )


def keycloak_resource_permission(
    token: str, *, resource_type: str, resource_ref: str, scope: str,
) -> bool:
    """Authorize one stable TradeResearch object reference and scope."""
    uri = keycloak_resource_uri(resource_type, resource_ref)
    name = keycloak_resource_name(resource_type, resource_ref)
    permission_scope = str(scope or "").strip()
    if not permission_scope:
        return False
    return keycloak_authorized_many(
        token, permissions=[(uri, name, permission_scope)],
    ).get((uri, permission_scope), False)


def keycloak_authorized_factor_sources(
    token: str,
    *,
    refs: list[tuple[str, str]],
    scope: str = "read",
) -> set[tuple[str, str]]:
    """Return the factor-source refs the caller may access in bounded batches."""
    normalized = list(dict.fromkeys(
        (str(owner or "").strip(), str(factor_id or "").strip())
        for owner, factor_id in refs
        if str(owner or "").strip() and str(factor_id or "").strip()
    ))
    if not normalized:
        return set()
    return keycloak_authorized_objects(
        token,
        resource_type="factor_source",
        refs=[(f"custom:{owner}:{factor_id}", (owner, factor_id))
              for owner, factor_id in normalized],
        scope=scope,
    )


def keycloak_authorized_objects(
    token: str,
    *,
    resource_type: str,
    refs: list[tuple[str, object]],
    scope: str,
) -> set[object]:
    """Batch-authorize stable object refs and return caller-provided labels."""
    normalized_scope = str(scope or "").strip()
    if not normalized_scope:
        return set()
    candidates: list[tuple[str, object, str, str]] = []
    seen: set[str] = set()
    for resource_ref, label in refs:
        resource_ref = str(resource_ref or "").strip()
        if not resource_ref or resource_ref in seen:
            continue
        seen.add(resource_ref)
        uri = keycloak_resource_uri(resource_type, resource_ref)
        name = keycloak_resource_name(resource_type, resource_ref)
        candidates.append((uri, label, name, normalized_scope))
    permissions = [(uri, name, permission_scope)
                   for uri, _label, name, permission_scope in candidates]
    allowed: set[object] = set()
    for offset in range(0, len(permissions), 256):
        result = keycloak_authorized_many(
            token, permissions=permissions[offset:offset + 256],
        )
        allowed.update(
            label for uri, label, _name, permission_scope in candidates[offset:offset + 256]
            if result.get((uri, permission_scope), False)
        )
    return allowed


def keycloak_request_identity() -> VerifiedRequestIdentity | None:
    """Return verified OIDC request identity without decoding the JWT.

    ``current_user``/the login decorator verifies the session first and stores
    its claims in Flask ``g``. Never decode an unverified JWT to obtain the
    subject, and never substitute a username for Keycloak's stable subject ID.
    """
    try:
        from flask import g, has_request_context, request

        if not has_request_context():
            return None
        identity = getattr(g, "keycloak_user_session", None)
        if not isinstance(identity, dict):
            return None
        subject = str(identity.get("keycloak_subject") or "").strip()
        issuer = str(identity.get("keycloak_issuer") or "").strip()
        username = str(identity.get("username") or "").strip()
        # Keep and reuse the exact token whose claims populated ``g``. Reading
        # the header again here could pair a previously verified cookie session
        # with a different, unverified Bearer token.
        token = str(getattr(g, "keycloak_access_token", "") or "").strip()
        if not subject or not issuer or not username or not token:
            return None
        return VerifiedRequestIdentity(token, issuer, subject, username)
    except Exception:
        return None


def keycloak_request_credentials() -> tuple[str, str, str] | None:
    """Compatibility projection of (token, subject, username)."""
    identity = keycloak_request_identity()
    if identity is None:
        return None
    return identity.token, identity.subject, identity.username


def _protection_request(settings: dict[str, str], token: str, method: str,
                        path: str, payload: dict | None = None) -> tuple[int, dict, str]:
    """Issue one bounded call to Keycloak's UMA Protection API."""
    from server.manager.domain.federation_transport import FederationTransport

    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"{_backchannel(settings)}/realms/{settings['realm']}/authz/protection/{path.lstrip('/')}",
        data=body, method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if body is not None else {}),
        },
    )
    with FederationTransport().open(request, timeout=3.0) as response:
        raw = response.read(64 * 1024 + 1)
        if len(raw) > 64 * 1024:
            raise ValueError("Keycloak resource response exceeds budget")
        location = str(response.headers.get("Location") or "")
        return response.status, json.loads(raw) if raw else {}, location


def ensure_keycloak_resource(
    *, resource_type: str, resource_ref: str, owner_subject: str,
) -> str:
    """Idempotently register a user-authorized object in Keycloak.

    A Keycloak client with service-account ``uma_protection`` is required.
    Existing object grants remain managed by Keycloak; this function only
    registers the resource identity and its scopes.
    """
    resource_name = keycloak_resource_name(resource_type, resource_ref)
    owner_subject = str(owner_subject or "").strip()
    if not owner_subject or len(owner_subject) > 255:
        raise ValueError("Keycloak resource owner subject is required")
    resource_uri = keycloak_resource_uri(resource_type, resource_ref)
    settings = oidc_settings()
    client = ServiceOIDCClient(
        _backchannel(settings), settings["realm"], settings["authz_client_id"],
        client_secret=settings["authz_client_secret"], timeout=3.0,
    )
    pat = str(client.client_credentials().get("access_token") or "")
    if not pat:
        raise AuthorizationUnavailable("Keycloak did not issue a Protection API token")

    query = urlencode({"name": resource_name, "first": 0, "max": 10, "deep": "true"})
    try:
        _, result, _ = _protection_request(settings, pat, "GET", f"resource_set?{query}")
    except Exception as exc:
        raise AuthorizationUnavailable("Keycloak resource lookup failed") from exc
    rows = result if isinstance(result, list) else result.get("resources", []) if isinstance(result, dict) else []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict) or str(row.get("name") or "") != resource_name:
                continue
            resource_id = str(row.get("_id") or row.get("id") or "").strip()
            if not resource_id:
                continue
            if row.get("attributes", {}).get("traderesearch_owner_subject") != [owner_subject]:
                raise AuthorizationUnavailable("Keycloak resource is owned by a different subject")
            uris = row.get("uris") or ([row.get("uri")] if row.get("uri") else [])
            if resource_uri not in {str(uri) for uri in uris if uri}:
                body = {
                    "_id": resource_id,
                    "name": resource_name,
                    "type": f"urn:traderesearch:resource:{str(resource_type).strip()}",
                                        "ownerManagedAccess": True,
                    "uris": [resource_uri],
                    "resource_scopes": list(_RESOURCE_SCOPES),
                    "attributes": {"traderesearch_owner_subject": [owner_subject], "traderesearch_ref_hash": [hashlib.sha256(
                        str(resource_ref).encode("utf-8")
                    ).hexdigest()]},
                }
                try:
                    _protection_request(
                        settings, pat, "PUT", f"resource_set/{resource_id}", body,
                    )
                except Exception as exc:
                    raise AuthorizationUnavailable("Keycloak resource URI update failed") from exc
                try:
                    _, confirmed, _ = _protection_request(
                        settings, pat, "GET", f"resource_set/{resource_id}",
                    )
                except Exception as exc:
                    raise AuthorizationUnavailable("Keycloak resource URI could not be verified") from exc
                confirmed_uris = confirmed.get("uris") or (
                    [confirmed.get("uri")] if confirmed.get("uri") else []
                )
                if resource_uri not in {str(uri) for uri in confirmed_uris if uri}:
                    raise AuthorizationUnavailable("Keycloak resource URI update did not persist")
            _ensure_owner_policy(settings, pat, resource_id, resource_name, owner_subject)
            return resource_id

    body = {
        "name": resource_name,
        "type": f"urn:traderesearch:resource:{str(resource_type).strip()}",
                "ownerManagedAccess": True,
        "uris": [resource_uri],
        "resource_scopes": list(_RESOURCE_SCOPES),
        "attributes": {"traderesearch_owner_subject": [owner_subject], "traderesearch_ref_hash": [hashlib.sha256(
            str(resource_ref).encode("utf-8")
        ).hexdigest()]},
    }
    try:
        _, result, location = _protection_request(settings, pat, "POST", "resource_set", body)
    except Exception as exc:
        raise AuthorizationUnavailable("Keycloak resource registration failed") from exc
    resource_id = str(result.get("_id") or result.get("id") or "").strip()
    if not resource_id and location:
        resource_id = location.rstrip("/").rsplit("/", 1)[-1]
    if not resource_id:
        # Some Keycloak versions return 204 or omit the ID on create. Requery
        # by the unique opaque resource name instead of guessing its identity.
        try:
            _, result, _ = _protection_request(settings, pat, "GET", f"resource_set?{query}")
        except Exception as exc:
            raise AuthorizationUnavailable("Keycloak resource could not be confirmed") from exc
        rows = result if isinstance(result, list) else result.get("resources", []) if isinstance(result, dict) else []
        resource_id = next((str(row.get("_id") or row.get("id") or "")
                            for row in rows if isinstance(row, dict)
                            and str(row.get("name") or "") == resource_name), "")
    if not resource_id:
        raise AuthorizationUnavailable("Keycloak resource registration returned no identity")
    _ensure_owner_policy(settings, pat, resource_id, resource_name, owner_subject)
    return resource_id


def delete_keycloak_resource(
    *, resource_type: str, resource_ref: str, owner_subject: str = "",
) -> bool:
    """Delete an exact TradeResearch resource after its source is retired.

    A missing resource is an idempotent no-op. If an expected owner is given,
    refuse to delete a resource owned by a different Keycloak subject.
    """
    resource_name = keycloak_resource_name(resource_type, resource_ref)
    expected_owner = str(owner_subject or "").strip()
    settings = oidc_settings()
    client = ServiceOIDCClient(
        _backchannel(settings), settings["realm"], settings["authz_client_id"],
        client_secret=settings["authz_client_secret"], timeout=3.0,
    )
    try:
        pat = str(client.client_credentials().get("access_token") or "")
        if not pat:
            raise AuthorizationUnavailable("Keycloak did not issue a Protection API token")
        query = urlencode({"name": resource_name, "first": 0, "max": 10, "deep": "true"})
        _, result, _ = _protection_request(settings, pat, "GET", f"resource_set?{query}")
        rows = result if isinstance(result, list) else result.get("resources", []) if isinstance(result, dict) else []
        matches = [row for row in rows if isinstance(row, dict)
                   and str(row.get("name") or "") == resource_name]
        if len(matches) > 1:
            raise AuthorizationUnavailable("duplicate Keycloak resource names")
        if not matches:
            return False
        resource_id = str(matches[0].get("_id") or matches[0].get("id") or "").strip()
        if expected_owner and matches[0].get("attributes", {}).get(
            "traderesearch_owner_subject"
        ) != [expected_owner]:
            raise AuthorizationUnavailable("refusing to delete a resource owned by another subject")
        if not resource_id:
            raise AuthorizationUnavailable("Keycloak resource has no identity")
        _protection_request(settings, pat, "DELETE", f"resource_set/{resource_id}")
        return True
    except AuthorizationUnavailable:
        raise
    except Exception as exc:
        raise AuthorizationUnavailable("Keycloak resource deletion failed") from exc


def _ensure_owner_policy(settings: dict[str, str], token: str, resource_id: str,
                         resource_name: str, owner_subject: str) -> None:
    """Ensure the Keycloak subject owning a private resource can manage it."""
    # Keycloak 26.8 pins Protection API ownership to the resource server.
    # User ownership is expressed by a stable subject attribute and UMA policy.
    _, resource, _ = _protection_request(
        settings, token, "GET", f"resource_set/{resource_id}",
    )
    if resource.get("attributes", {}).get("traderesearch_owner_subject") != [owner_subject]:
        raise AuthorizationUnavailable("Keycloak resource owner was not confirmed")
    from server.identity.federation_identity_sync import manager_keycloak_admin_adapter

    user = manager_keycloak_admin_adapter()._get(f"users/{owner_subject}")
    if not isinstance(user, dict) or user.get("id") != owner_subject or not user.get("username"):
        raise AuthorizationUnavailable("Keycloak owner identity was not confirmed")
    owner_labels = {owner_subject, str(user["username"])}
    policy_name = f"{resource_name}:owner"
    query = urlencode({"resource": resource_id, "first": 0, "max": 100})
    try:
        _, result, _ = _protection_request(
            settings, token, "GET", f"uma-policy?{query}",
        )
    except Exception as exc:
        raise AuthorizationUnavailable("Keycloak owner policy lookup failed") from exc
    rows = result if isinstance(result, list) else result.get("permissions", []) if isinstance(result, dict) else []
    matches = [row for row in rows if isinstance(row, dict)
               and str(row.get("name") or "") == policy_name]
    if len(matches) > 1:
        raise AuthorizationUnavailable("duplicate Keycloak owner policies")
    expected_scopes = sorted(_RESOURCE_SCOPES)
    if matches:
        policy = matches[0]
        users = sorted(str(value) for value in policy.get("users", []) if value)
        scopes = sorted(str(value) for value in policy.get("scopes", []) if value)
        if (len(users) != 1 or users[0] not in owner_labels) or scopes != expected_scopes:
            raise AuthorizationUnavailable("conflicting Keycloak owner policy")
        return
    body = {
        "name": policy_name,
        "description": "TradeResearch resource owner access",
        "users": [owner_subject],
        "scopes": expected_scopes,
        "logic": "POSITIVE",
    }
    try:
        _protection_request(
            settings, token, "POST", f"uma-policy/{resource_id}", body,
        )
        _, result, _ = _protection_request(
            settings, token, "GET", f"uma-policy?{query}",
        )
    except Exception as exc:
        raise AuthorizationUnavailable("Keycloak owner policy could not be created") from exc
    rows = result if isinstance(result, list) else result.get("permissions", []) if isinstance(result, dict) else []
    matches = [row for row in rows if isinstance(row, dict)
               and str(row.get("name") or "") == policy_name]
    if len(matches) != 1:
        raise AuthorizationUnavailable("Keycloak owner policy was not confirmed")
    users = sorted(str(value) for value in matches[0].get("users", []) if value)
    scopes = sorted(str(value) for value in matches[0].get("scopes", []) if value)
    if (len(users) != 1 or users[0] not in owner_labels) or scopes != expected_scopes:
        raise AuthorizationUnavailable("Keycloak owner policy verification failed")
