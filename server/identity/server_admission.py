"""Keycloak-owned Manager admission policy, shared by both HTTP adapters.

The deployment supplies only its stable server ID and expected organization;
Keycloak must confirm the reciprocal binding and current user permissions.
Successful lookups are cached for at most five seconds, then rechecked. An
unavailable provider, incomplete binding or conflicting identity denies
admission. Visitor and machine-service capabilities have separate policies.
"""
from __future__ import annotations

from collections import OrderedDict
import os
import threading
import time
from urllib.parse import quote, urlencode

from server.identity.realm_groups import component, organization_group_path
from server.identity.user_session import may_login_public_server, oidc_settings

_TTL = 5.0
_CACHE_LIMIT = 512
_CACHE: OrderedDict[tuple, tuple[float, object]] = OrderedDict()
_CACHE_LOCK = threading.Lock()
_STRIPES = tuple(threading.Lock() for _ in range(32))


def _cached(key, loader):
    def lookup():
        with _CACHE_LOCK:
            item = _CACHE.get(key)
            if item and item[0] > time.monotonic():
                _CACHE.move_to_end(key)
                return True, item[1]
            if item:
                _CACHE.pop(key, None)
            return False, None
    found, value = lookup()
    if found:
        return value
    with _STRIPES[hash(key) % len(_STRIPES)]:
        found, value = lookup()
        if found:
            return value
        value = loader()
        with _CACHE_LOCK:
            _CACHE[key] = (time.monotonic() + _TTL, value)
            _CACHE.move_to_end(key)
            while len(_CACHE) > _CACHE_LIMIT:
                _CACHE.popitem(last=False)
        return value


def clear_server_admission_cache():
    """Discard projections after an administrative binding or role change."""
    with _CACHE_LOCK:
        _CACHE.clear()


def manager_binding_group_path(server_id: str) -> str:
    return "/traderesearch/internal-managers/" + component("manager", server_id)


def _group(adapter, path):
    row = adapter._get("group-by-path/" + quote(path.lstrip("/"), safe="/"))
    if not isinstance(row, dict) or row.get("path") != path or not row.get("id"):
        raise ValueError("Keycloak Manager binding group is missing or ambiguous")
    attributes = row.get("attributes")
    if not isinstance(attributes, dict):
        raise ValueError("Keycloak Manager binding attributes are missing")
    return attributes


def _internal_binding(adapter, server_id, organization_id):
    organization = _group(adapter, organization_group_path(organization_id))
    manager = _group(adapter, manager_binding_group_path(server_id))
    return (organization.get("tr_internal_manager_id") == [server_id]
            and manager.get("tr_internal_manager_id") == [server_id]
            and manager.get("tr_organization_id") == [organization_id])


def _organization_roots(groups):
    if not isinstance(groups, (list, tuple, set, frozenset)):
        return None
    prefix = "/traderesearch/organizations/"
    roots = set()
    for value in groups:
        if not isinstance(value, str) or not value.startswith("/") or "//" in value:
            return None
        if value.startswith(prefix):
            part = value[len(prefix):].split("/", 1)[0]
            if not part:
                return None
            roots.add(prefix + part)
    return roots


def _user(adapter, subject):
    row = adapter._get("users/" + quote(subject, safe=""))
    if not isinstance(row, dict) or row.get("id") != subject or row.get("enabled") is not True:
        return None
    return row


def _internal_user(adapter, subject, organization_id):
    user = _user(adapter, subject)
    if not user or (user.get("attributes") or {}).get("tr_organization_id") != [organization_id]:
        return False
    return _organization_roots(adapter.user_group_paths(subject)) == {
        organization_group_path(organization_id),
    }


def _roles_client(adapter, client_id):
    rows = adapter._get("clients?" + urlencode({"clientId": client_id}))
    if not isinstance(rows, list):
        raise ValueError("Keycloak role client lookup failed")
    matches = [row for row in rows if isinstance(row, dict)
               and row.get("clientId") == client_id and row.get("id")]
    if len(matches) != 1 or matches[0].get("enabled") is False:
        raise ValueError("Keycloak role client is missing or ambiguous")
    return str(matches[0]["id"])


def _public_user(adapter, subject, client_id, issuer):
    if not _user(adapter, subject):
        return False
    client_uuid = _cached(("client", issuer, client_id), lambda: _roles_client(adapter, client_id))
    path = ("users/" + quote(subject, safe="") + "/role-mappings/clients/"
            + quote(client_uuid, safe="") + "/composite")
    rows = adapter._get(path)
    if not isinstance(rows, list):
        raise ValueError("Keycloak effective role response is invalid")
    return any(isinstance(row, dict) and row.get("name") == "public_server:login" for row in rows)


def _environment_value(name, convert):
    newer = os.environ.get("TRADERESEARCH_" + name)
    older = os.environ.get("FACTORTESTER_" + name)
    if newer is not None and older is not None and convert(newer) != convert(older):
        raise ValueError("conflicting Manager deployment configuration")
    value = newer if newer is not None else older
    return (convert(value), True) if value is not None else (None, False)


def _boolean(value):
    selected = str(value or "").strip().lower()
    if selected in {"1", "true", "yes", "on"}:
        return True
    if selected in {"0", "false", "no", "off", ""}:
        return False
    raise ValueError("invalid Manager deployment flag")


def _context(state):
    from server.manager.domain.organization_scope import normalize_managed_organizations

    public, public_set = _environment_value("PUBLIC_SERVER", _boolean)
    device, device_set = _environment_value("REQUIRE_DEVICE_AUTH", _boolean)
    server_id, server_set = _environment_value("SERVER_ID", lambda value: str(value).strip())
    organizations, org_set = _environment_value("MANAGED_ORGANIZATIONS", normalize_managed_organizations)
    if not public_set:
        public, public_set = (device, True) if device_set else (False, False)
    if state is None:
        return bool(public), str(server_id or ""), tuple(organizations or ())
    state_public = bool(getattr(state, "public_server", False))
    state_server = str(getattr(state, "server_id", "") or "").strip()
    state_orgs = tuple(getattr(state, "managed_organizations", ()) or ())
    if ((public_set and public != state_public)
            or (server_set and server_id != state_server)
            or (org_set and organizations != state_orgs)):
        raise ValueError("Manager and service deployment configuration disagree")
    return state_public, state_server, state_orgs


def server_admission(session, *, state=None):
    """Return ``(allowed, code)`` for an already verified Keycloak session."""
    if not isinstance(session, dict):
        return False, "unverified"
    subject = str(session.get("keycloak_subject") or "").strip()
    issuer = str(session.get("keycloak_issuer") or "").strip().rstrip("/")
    if not subject or len(subject) > 512 or not issuer:
        return False, "unverified"
    try:
        public, server_id, organizations = _context(state)
        if public and not may_login_public_server(session):
            return False, "public_login_denied"
        if not public:
            if not server_id or len(server_id) > 256 or len(organizations) != 1:
                return False, "server_organization_unconfigured"
            org = organizations[0]
            if (session.get("organization_id") != org
                    or _organization_roots(session.get("keycloak_groups")) != {organization_group_path(org)}):
                return False, "organization_login_denied"
        settings = oidc_settings()
        if settings["issuer"].rstrip("/") != issuer:
            return False, "unverified"
        from server.identity.federation_identity_sync import manager_keycloak_admin_adapter
        adapter = None

        def provider():
            nonlocal adapter
            if adapter is None:
                adapter = manager_keycloak_admin_adapter()
            return adapter

        if public:
            client_id = settings["roles_client_id"]
            # FGAP view permission can expose the selected client's own
            # installation credentials. Never expand the runtime's access to
            # a different client's secret merely to inspect role mappings.
            if client_id != settings["client_id"]:
                return False, "server_authorization_unavailable"
            allowed = _cached(("public-user", issuer, subject, client_id),
                              lambda: _public_user(provider(), subject, client_id, issuer))
            return bool(allowed), "" if allowed else "public_login_denied"
        binding = _cached(("binding", issuer, server_id, org),
                          lambda: _internal_binding(provider(), server_id, org))
        if not binding:
            return False, "server_organization_conflict"
        allowed = _cached(("internal-user", issuer, subject, org),
                          lambda: _internal_user(provider(), subject, org))
        return bool(allowed), "" if allowed else "organization_login_denied"
    except Exception:
        # No Keycloak error, timeout or malformed result is an authorization.
        return False, "server_authorization_unavailable"
