"""Bounded, short-lived Keycloak directory projections for admin UI.

The directory is a read model, never an authorization store. Callers must pass
verified Keycloak claims; the group scope is derived from those claims before
any Keycloak query. Object access continues to use Keycloak Authorization
Services at the object boundary.
"""

from __future__ import annotations

from collections import OrderedDict
import threading
import time
from typing import Any

from server.identity.federation_identity_sync import manager_keycloak_admin_adapter
from server.identity.realm_groups import managed_member_group_paths


_CACHE_TTL = 15.0
_CACHE_LIMIT = 4
_CACHE_LOCK = threading.Lock()
_CACHE: OrderedDict[tuple[str, str], tuple[float, tuple[dict[str, Any], ...]]] = OrderedDict()


def _attribute(identity: object, key: str) -> str:
    attributes = getattr(identity, "attributes", None)
    values = attributes.get(key) if isinstance(attributes, dict) else None
    if isinstance(values, (tuple, list)) and values:
        return str(values[0] or "").strip()
    return ""


def _project(identity: object) -> dict[str, Any]:
    username = str(getattr(identity, "username", "") or "").strip()
    display_name = str(getattr(identity, "display_name", "") or "").strip()
    groups = tuple(sorted({
        str(path).rstrip("/") for path in (getattr(identity, "groups", ()) or ())
        if isinstance(path, str) and path.startswith("/traderesearch/")
    }))
    return {
        "username": username,
        "alias": display_name or username,
        "active": getattr(identity, "enabled", None) is True,
        "keycloak_subject": str(getattr(identity, "subject", "") or ""),
        "tr_identity_id": _attribute(identity, "tr_identity_id"),
        "organization_id": _attribute(identity, "tr_organization_id"),
        "organization_name": _attribute(identity, "tr_organization_name"),
        "level_id": _attribute(identity, "tr_level_id"),
        "parent_username": _attribute(identity, "tr_parent_username"),
        "groups": groups,
        "role": _role(identity, groups),
    }


def _role(identity: object, groups: tuple[str, ...]) -> str:
    roles = set(getattr(identity, "roles", ()) or ())
    if "admin_console:manage" in roles:
        return "super_admin"
    from server.identity.realm_groups import administrative_group_role

    scoped = administrative_group_role(groups)
    return scoped if scoped in {"org_admin", "level_admin"} else "user"


def _cached_group_tree_members(adapter: object, path: str) -> tuple[dict[str, Any], ...]:
    base_url = str(getattr(adapter, "base_url", "") or "")
    realm = str(getattr(adapter, "realm", "") or "")
    key = (f"{base_url}/realms/{realm}", path)
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is not None and cached[0] > now:
            _CACHE.move_to_end(key)
            return cached[1]
        if cached is not None:
            _CACHE.pop(key, None)

    reader = getattr(adapter, "group_tree_members", None)
    if not callable(reader):
        raise RuntimeError("Keycloak adapter does not provide bounded group directory reads")
    rows = reader(path, max_groups=4096, max_users=20_000)
    projected = tuple(
        _project(identity) for identity in rows
        if str(getattr(identity, "username", "") or "").strip()
    )
    with _CACHE_LOCK:
        _CACHE[key] = (time.monotonic() + _CACHE_TTL, projected)
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_LIMIT:
            _CACHE.popitem(last=False)
    return projected


def managed_users_for_verified_request(
    principal: object, *, include_self: bool = False, max_users: int = 20_000,
) -> list[dict[str, Any]]:
    """Return the verified request's Keycloak-managed user subtree.

    This is a directory projection for UI/catalog fan-out only. It is never an
    object authorization decision; callers must still check FGAP for each
    protected resource. No caller-provided group path can widen the scope.
    """
    selected_principal = str(principal or "").strip()
    try:
        selected_max_users = int(max_users)
    except (TypeError, ValueError):
        raise ValueError("managed directory limit must be an integer") from None
    if not selected_principal or not 1 <= selected_max_users <= 20_000:
        return []
    try:
        from flask import g, has_request_context

        if not has_request_context():
            return []
        identity = getattr(g, "keycloak_user_session", None)
        if (not isinstance(identity, dict)
                or str(identity.get("username") or "").strip() != selected_principal):
            return []
        request_cache = getattr(g, "tr_managed_user_directory", None)
        if isinstance(request_cache, dict) and selected_principal in request_cache:
            cached_users = request_cache[selected_principal]
            return [row for row in cached_users
                    if include_self or str(row.get("username") or "") != selected_principal]
        groups = identity.get("keycloak_groups", ())
        roles = identity.get("keycloak_roles", ())
        first = users_in_admin_scope(
            groups=groups, roles=roles, limit=min(200, selected_max_users), offset=0,
        )
        users = list(first["users"])
        total = int(first.get("total") or 0)
        offset = len(users)
        while offset < total and offset < selected_max_users:
            page = users_in_admin_scope(
                groups=groups, roles=roles,
                limit=min(200, selected_max_users - offset), offset=offset,
            )
            next_users = list(page["users"])
            if not next_users:
                raise RuntimeError("Keycloak directory pagination made no progress")
            users.extend(next_users)
            offset += len(next_users)
        if offset < total:
            raise RuntimeError("Keycloak managed directory exceeds its configured limit")
        if not isinstance(request_cache, dict):
            request_cache = {}
            g.tr_managed_user_directory = request_cache
        request_cache[selected_principal] = tuple(users)
        return [row for row in users
                if include_self or str(row.get("username") or "") != selected_principal]
    except ImportError:
        return []


def users_in_admin_scope(
    *, groups: object, roles: object, query: object = "", limit: int = 100,
    offset: int = 0, adapter: object | None = None,
) -> dict[str, Any]:
    """List active Keycloak users visible to a verified admin, with paging.

    Super administrators query the TradeResearch group tree. Organization and
    level administrators can only query the nested member roots derived from
    their signed Realm Group claims. No username, organization, or group path
    supplied by the browser can widen that scope.
    """
    try:
        selected_limit = int(limit)
        selected_offset = int(offset)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid directory pagination") from exc
    if not 1 <= selected_limit <= 200 or not 0 <= selected_offset <= 20_000:
        raise ValueError("directory pagination is outside the allowed range")
    identities = _users_in_admin_scope(
        groups=groups, roles=roles, adapter=adapter,
    )
    needle = str(query or "").strip().casefold()
    values = [row for row in identities
              if row.get("active") is True
              and (not needle or needle in str(row.get("username") or "").casefold()
                   or needle in str(row.get("alias") or "").casefold())]
    selected_limit = int(limit)
    selected_offset = int(offset)
    return {
        "users": values[selected_offset:selected_offset + selected_limit],
        "total": len(values),
        "offset": selected_offset,
        "limit": selected_limit,
        "has_more": selected_offset + selected_limit < len(values),
    }


def managed_users_for_claims(
    *, groups: object, roles: object, adapter: object | None = None,
    max_users: int = 20_000,
) -> list[dict[str, Any]]:
    """Return the bounded active directory beneath verified Keycloak claims.

    This helper is for request handlers which already hold a verified Manager
    session but do not run inside Flask's request context (for example the
    native Manager HTTP server). The caller must never pass browser-supplied
    group paths or roles.
    """
    try:
        selected_max = int(max_users)
    except (TypeError, ValueError):
        raise ValueError("managed directory limit must be an integer") from None
    if not 1 <= selected_max <= 20_000:
        raise ValueError("managed directory limit is outside the allowed range")
    return _users_in_admin_scope(
        groups=groups, roles=roles, adapter=adapter,
        max_users=selected_max,
    )


def _users_in_admin_scope(
    *, groups: object, roles: object, adapter: object | None = None,
    max_users: int = 20_000,
) -> list[dict[str, Any]]:
    role_set = {str(value) for value in roles or ()}
    if "admin_console:manage" in role_set:
        paths = ("/traderesearch",)
    else:
        paths = tuple(sorted(managed_member_group_paths(groups)))
        if not paths:
            raise PermissionError("Keycloak identity administration permission required")

    source = adapter or manager_keycloak_admin_adapter()
    identities: dict[str, dict[str, Any]] = {}
    for path in paths:
        for row in _cached_group_tree_members(source, path):
            username = str(row.get("username") or "").strip()
            if not username:
                continue
            previous = identities.get(username)
            if previous is None:
                identities[username] = row
            else:
                combined_groups = tuple(sorted(set(previous.get("groups", ())) | set(row.get("groups", ()))))
                identities[username] = {**previous, **{
                    key: previous.get(key) or row.get(key)
                    for key in (
                        "tr_identity_id", "organization_id", "organization_name",
                        "level_id", "parent_username",
                    )
                }, "groups": combined_groups}
            if len(identities) > max_users:
                raise RuntimeError("Keycloak managed directory exceeds its configured limit")

    values = [row for row in identities.values() if row.get("active") is True]
    values.sort(key=lambda row: (
        str(row.get("alias") or "").casefold(),
        str(row.get("username") or "").casefold(),
    ))
    if len(values) > max_users:
        raise RuntimeError("Keycloak managed directory exceeds its configured limit")
    return values


def clear_directory_cache() -> None:
    """Clear only the bounded volatile UI projection (primarily for tests)."""
    with _CACHE_LOCK:
        _CACHE.clear()
