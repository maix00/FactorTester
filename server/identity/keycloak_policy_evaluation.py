"""Bounded administrative Keycloak Policy Evaluation for exact subjects.

This is not an end-user bearer-token authorization shortcut. Callers must
explicitly select their allowed resource types and scopes.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any, Callable
from urllib.parse import quote, urlencode
from urllib.request import Request

from server.identity.keycloak_authorization import (
    AuthorizationUnavailable, lookup_keycloak_resource, protection_token as protection_token_for,
)

_BATCH_RESOURCES = 32
_MAX_RESOURCES = 20_000
_RESPONSE_LIMIT = 2 * 1024 * 1024


def _policy_evaluation_request(adapter, client_uuid: str, payload: dict[str, Any]) -> dict[str, Any]:
    from server.manager.domain.federation_transport import FederationTransport

    request = Request(
        f"{adapter.base_url}/admin/realms/{quote(adapter.realm, safe='')}/clients/"
        f"{quote(client_uuid, safe='')}/authz/resource-server/policy/evaluate",
        data=json.dumps(payload).encode(), method="POST",
        headers={"Authorization": f"Bearer {adapter._token()}", "Content-Type": "application/json"},
    )
    with FederationTransport().open(request, timeout=adapter.timeout) as response:
        raw = response.read(_RESPONSE_LIMIT + 1)
    if len(raw) > _RESPONSE_LIMIT:
        raise AuthorizationUnavailable("Keycloak evaluation response exceeds budget")
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise AuthorizationUnavailable("Keycloak evaluation response is invalid")
    return result


class KeycloakPolicyEvaluator:
    """Evaluate explicit resource/scope decisions for one real user.

    Resource IDs are resolved against the real Protection API once per
    evaluator, while decisions are fetched afresh for each subject. Results
    include explicit denials so callers cannot confuse a missing response with
    an evaluated denial. The object should be used only for a bounded cutover
    audit; it is not a cross-request authorization cache.
    """

    def __init__(self, *, allowed_kinds: Iterable[str], allowed_scopes: Iterable[str], adapter=None, settings: dict[str, str] | None = None,
                 protection_token: str | None = None,
                 resource_lookup: Callable | None = None,
                 request: Callable = _policy_evaluation_request) -> None:
        if adapter is None:
            from server.identity.federation_identity_sync import manager_keycloak_admin_adapter
            adapter = manager_keycloak_admin_adapter()
        if settings is None:
            from server.identity.user_session import oidc_settings
            settings = oidc_settings()
        self.adapter, self.settings, self.request = adapter, settings, request
        self.allowed_kinds, self.allowed_scopes = frozenset(allowed_kinds), frozenset(allowed_scopes)
        if not self.allowed_kinds or not self.allowed_scopes:
            raise ValueError("allowed resource kinds and scopes are required")
        self._token = protection_token or protection_token_for(settings)
        self._lookup = resource_lookup or lookup_keycloak_resource
        self._resolved: dict[tuple[str, str], str] = {}
        self._resource_ids: set[str] = set()
        client_id = str(settings.get("authz_client_id") or "").strip()
        if not client_id:
            raise AuthorizationUnavailable("Keycloak resource client is not configured")
        rows = adapter._get("clients?" + urlencode({"clientId": client_id, "first": 0, "max": 3}))
        matches = [row for row in rows if isinstance(row, dict) and row.get("clientId") == client_id]
        if len(matches) != 1 or not matches[0].get("id"):
            raise AuthorizationUnavailable("Keycloak resource client is missing or ambiguous")
        self._client_uuid = str(matches[0]["id"])

    def _resource_id(self, kind: str, ref: str) -> str:
        key = (kind, ref)
        if key not in self._resolved:
            row = self._lookup(self.settings, self._token, kind, ref)
            identifier = str(row.get("_id") or row.get("id") or "").strip()
            if not identifier:
                raise AuthorizationUnavailable("Keycloak resource has no ID")
            if identifier in self._resource_ids:
                raise AuthorizationUnavailable("Keycloak resources do not have distinct IDs")
            self._resolved[key] = identifier
            self._resource_ids.add(identifier)
        return self._resolved[key]

    def evaluate(self, identity_id: str, *,
                 candidates: Iterable[tuple[str, str, tuple[str, ...]]]) -> dict[tuple[str, str, str], bool]:
        stable = str(identity_id or "").strip()
        if not stable or len(stable) > 128:
            raise ValueError("stable identity is required")
        user = self.adapter.user_by_identity_id(stable)
        attrs = user.get("attributes") if isinstance(user, dict) else None
        subject = str(user.get("id") or "") if isinstance(user, dict) else ""
        if (not subject or user.get("enabled") is not True or not isinstance(attrs, dict)
                or attrs.get("tr_identity_id") != [stable]):
            raise AuthorizationUnavailable("Keycloak audit identity is unavailable or ambiguous")

        requested: dict[tuple[str, str], set[str]] = {}
        for kind, ref, scopes in candidates:
            kind, ref = str(kind or "").strip(), str(ref or "").strip()
            scope_set = set(scopes)
            if (kind not in self.allowed_kinds or not ref or len(ref) > 2048 or not scope_set
                    or any(scope not in self.allowed_scopes for scope in scope_set)):
                raise ValueError("invalid authorization candidate")
            requested.setdefault((kind, ref), set()).update(scope_set)
            if len(requested) > _MAX_RESOURCES:
                raise ValueError("authorization audit exceeds its resource budget")

        records = [(kind, ref, sorted(scopes), self._resource_id(kind, ref))
                   for (kind, ref), scopes in sorted(requested.items())]
        decisions: dict[tuple[str, str, str], bool] = {}
        # Keycloak can omit denied scopes when the same resource has multiple
        # requested scopes and at least one is permitted. Evaluate one scope
        # per resource, while still batching distinct resources in each call.
        for scope in sorted(self.allowed_scopes):
            scoped = [(kind, ref, resource_id) for kind, ref, scopes, resource_id in records if scope in scopes]
            for offset in range(0, len(scoped), _BATCH_RESOURCES):
                batch = scoped[offset:offset + _BATCH_RESOURCES]
                by_id = {resource_id: (kind, ref) for kind, ref, resource_id in batch}
                payload = {"userId": subject, "resources": [
                    {"_id": resource_id, "scopes": [{"name": scope}]}
                    for _kind, _ref, resource_id in batch
                ]}
                response = self.request(self.adapter, self._client_uuid, payload)
                rows = response.get("results") if isinstance(response, dict) else None
                if not isinstance(rows, list) or len(rows) != len(batch):
                    raise AuthorizationUnavailable("Keycloak evaluation omitted resources")
                seen: set[str] = set()
                for row in rows:
                    resource = row.get("resource") if isinstance(row, dict) else None
                    resource_id = str(resource.get("_id") or resource.get("id") or "") if isinstance(resource, dict) else ""
                    if resource_id not in by_id or resource_id in seen:
                        raise AuthorizationUnavailable("Keycloak evaluation returned an unexpected resource")
                    seen.add(resource_id)
                    kind, ref = by_id[resource_id]
                    scopes = row.get("scopes")
                    allowed = row.get("allowedScopes")
                    if (not isinstance(scopes, list) or not isinstance(allowed, list)
                            or any(not isinstance(item, dict) or not isinstance(item.get("name"), str)
                                   for item in [*scopes, *allowed])):
                        raise AuthorizationUnavailable("Keycloak evaluation omitted scope decisions")
                    actual_scopes = [item["name"] for item in scopes]
                    allowed_scopes = [item["name"] for item in allowed]
                    status = str(row.get("status") or "")
                    if (actual_scopes != [scope] or allowed_scopes not in ([], [scope])
                            or status not in {"PERMIT", "DENY"}
                            or (status == "PERMIT") != bool(allowed_scopes)):
                        raise AuthorizationUnavailable("Keycloak evaluation scope set changed")
                    decisions[(kind, ref, scope)] = bool(allowed_scopes)
        return decisions


