"""Keycloak decisions for source-owned Profile metadata and conversations.

Profile display labels and legacy ACL fields are never credentials. A source
Manager evaluates its own resources using the exact verified user token; a
foreign source must be queried through an authenticated delegation instead.
This adapter is not yet connected to the Profile directory: verified owner
bindings and per-object migration parity must be established before cutover.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from server.identity.keycloak_authorization import (
    AuthorizationUnavailable, keycloak_authorized_many, keycloak_request_identity,
    keycloak_resource_name, keycloak_resource_uri,
)


def profile_resource_ref(source_manager_id: str, owner_identity_id: str, profile_id: str) -> str:
    """Keep identical labels on different sources or owners distinct."""
    values = [str(value or "").strip() for value in (source_manager_id, owner_identity_id, profile_id)]
    if any(not value or len(value) > 512 for value in values):
        raise ValueError("Profile source, stable owner and Profile ID are required")
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def _owner(profile: dict[str, Any]) -> str:
    binding = profile.get("session_binding")
    if isinstance(binding, dict) and binding.get("principal_ref"):
        return str(binding["principal_ref"]).strip()
    return str(profile.get("owner_ref") or profile.get("principal") or profile.get("username") or "").strip()


class KeycloakProfileDirectoryAccess:
    """Read-only, bounded UMA batch adapter; no grant or local ACL fallback."""

    def __init__(self, *, manager_id: str, owner_identity: Callable[[str, str], str | None], adapter=None,
                 identity: Callable = keycloak_request_identity,
                 authorize: Callable = keycloak_authorized_many) -> None:
        self.manager_id = str(manager_id or "").strip()
        if not self.manager_id:
            raise ValueError("source Manager ID is required")
        if adapter is None:
            from server.identity.federation_identity_sync import manager_keycloak_admin_adapter
            adapter = manager_keycloak_admin_adapter()
        if not callable(owner_identity):
            raise ValueError("a verified Profile owner identity resolver is required")
        # Profile projections are mutable. A caller must resolve the frozen
        # identity from its verified registration or migration receipt, never
        # from fields supplied by a profile document or display name.
        self.owner_identity = owner_identity
        self.adapter, self.identity, self.authorize = adapter, identity, authorize

    def _stable_owner(self, owner: str, stable: str) -> str:
        # This binding is frozen by the reviewed migration or the creating
        # request; a legacy username alone must not authorize a replacement
        # account which happens to reuse it later.
        if not stable or len(stable) > 512:
            return ""
        try:
            row = self.adapter.user_by_identity_id(stable)
        except LookupError:
            return ""
        except Exception as exc:
            raise AuthorizationUnavailable("Keycloak Profile owner lookup is unavailable") from exc
        if row is None:
            return ""
        if not isinstance(row, dict) or row.get("enabled") is not True or not row.get("id"):
            return ""
        attrs = row.get("attributes")
        identity = attrs.get("tr_identity_id") if isinstance(attrs, dict) else None
        legacy = attrs.get("legacy_username") if isinstance(attrs, dict) else None
        if identity != [stable]:
            return ""
        if legacy is not None:
            if not isinstance(legacy, list) or len(legacy) != 1 or legacy[0] != owner:
                return ""
        elif str(row.get("username") or "").casefold() != owner.casefold():
            return ""
        return stable

    def access_many(self, *, viewer: str, profiles: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
        """Return explicit `read`/`use` decisions for bounded local candidates.

        Missing owner identities or foreign sources are denied with a repair
        reason. A Keycloak outage raises; it never turns into local visibility.
        """
        request = self.identity()
        if request is None or str(request.username) != str(viewer):
            raise PermissionError("verified Keycloak Profile viewer is required")
        if not isinstance(profiles, list) or len(profiles) > 20_000:
            raise ValueError("Profile authorization batch exceeds its budget")
        owners: dict[tuple[str, str], str] = {}
        entries: dict[tuple[str, str, str], tuple[str, str] | None] = {}
        decisions: dict[tuple[str, str, str], dict[str, Any]] = {}
        for profile in profiles:
            if not isinstance(profile, dict):
                raise ValueError("Profile candidate must be an object")
            source = str(profile.get("source_server_id") or self.manager_id).strip()
            owner, profile_id = _owner(profile), str(profile.get("profile_id") or "").strip()
            key = (source, owner, profile_id)
            if not source or not owner or not profile_id:
                raise ValueError("Profile candidate identity is incomplete")
            if source != self.manager_id:
                entries[key] = None
                decisions[key] = {"can_view": False, "can_view_conversations": False,
                                  "reason": "foreign_source_requires_delegation"}
                continue
            try:
                frozen = str(self.owner_identity(owner, profile_id) or "").strip()
            except Exception as exc:
                raise AuthorizationUnavailable("verified Profile owner binding is unavailable") from exc
            owner_key = (owner, frozen)
            if owner_key not in owners:
                owners[owner_key] = self._stable_owner(owner, frozen)
            stable = owners[owner_key]
            if not stable:
                entries[key] = None
                decisions[key] = {"can_view": False, "can_view_conversations": False,
                                  "reason": "owner_identity_needs_repair"}
                continue
            ref = profile_resource_ref(source, stable, profile_id)
            entries[key] = (keycloak_resource_uri("profile", ref), keycloak_resource_name("profile", ref))

        permissions = list(dict.fromkeys(
            (entry[0], entry[1], scope)
            for entry in entries.values() if entry is not None for scope in ("read", "use")
        ))
        results: dict[tuple[str, str], bool] = {}
        for offset in range(0, len(permissions), 256):
            results.update(self.authorize(request.token, permissions=permissions[offset:offset + 256], use_cache=False))
        for key, entry in entries.items():
            if entry is None:
                continue
            read = results.get((entry[0], "read")) is True
            use = results.get((entry[0], "use")) is True
            decisions[key] = {"can_view": read, "can_view_conversations": read and use,
                              "reason": "keycloak" if read else "keycloak_denied"}
        return decisions
