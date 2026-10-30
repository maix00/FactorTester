"""Idempotent Keycloak Realm Group and FGAP-v2 hierarchy provisioning.

This is an offline migration helper, not request-path authorization code. It
uses Keycloak's Admin REST API and only creates the deterministic groups,
policies, permissions, and user memberships present in a reviewed plan. It
never deletes or broadens an existing policy whose identity does not match.
"""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any
from urllib.parse import urlencode


_PAGE_SIZE = 500
_MAX_PAGES = 1000
_ALLOWED_GROUP_SCOPES = frozenset({
    "view", "manage", "view-members", "manage-members", "manage-membership",
})
_GROUP_ADMIN_CLIENT_ROLES = ("query-groups", "query-users")
_DANGEROUS_GROUP_ADMIN_ROLES = frozenset({
    "realm-admin", "manage-realm", "manage-users", "manage-authorization",
})
_GROUP_CLAIM_MAPPER_NAME = "traderesearch-realm-group-paths"
_BLOCKING_PLAN_KEYS = (
    "unsupported_legacy_roles", "scoped_legacy_roles_blocked", "hierarchy_errors",
    "unmapped_account_group_memberships", "invalid_admin_flags", "invalid_developer_flags",
)


class HierarchyProvisioningError(RuntimeError):
    """The Keycloak hierarchy could not be safely applied or verified."""


def _digest(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(raw.encode("utf-8")).hexdigest()[:16]


def _rows(value: object) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        # Some Keycloak minor versions wrap search results while others return
        # a bare list. Do not interpret arbitrary mapping values as resources.
        for key in ("resources", "policies", "permissions", "items"):
            rows = value.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        return [value] if value.get("id") or value.get("name") else []
    return []


def _exactly_one(rows: list[dict[str, Any]], *, what: str, name: str) -> dict[str, Any] | None:
    matches = [row for row in rows if str(row.get("name") or "") == name]
    if len(matches) > 1:
        raise HierarchyProvisioningError(f"duplicate Keycloak {what}: {name}")
    return matches[0] if matches else None


class KeycloakHierarchyProvisioner:
    """Provision a frozen hierarchy plan using a Keycloak Admin REST adapter."""

    def __init__(self, adapter) -> None:
        self.adapter = adapter

    def _page(self, path: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        separator = "&" if "?" in path else "?"
        for page in range(_MAX_PAGES):
            query = urlencode({"first": page * _PAGE_SIZE, "max": _PAGE_SIZE})
            rows = _rows(self.adapter._get(f"{path}{separator}{query}"))
            result.extend(rows)
            if len(rows) < _PAGE_SIZE:
                return result
        raise HierarchyProvisioningError("Keycloak list exceeds the migration page budget")

    def _all_groups(self) -> dict[str, dict[str, str]]:
        by_path: dict[str, dict[str, str]] = {}
        visited: set[str] = set()

        def walk(path: str, parent_id: str = "") -> None:
            endpoint = f"groups/{parent_id}/children" if parent_id else "groups"
            for raw in self._page(endpoint):
                group_id = str(raw.get("id") or "").strip()
                name = str(raw.get("name") or "").strip()
                if not group_id or not name:
                    raise HierarchyProvisioningError("Keycloak returned a group without id/name")
                group_path = str(raw.get("path") or f"{path}/{name}").rstrip("/")
                if not group_path.startswith("/"):
                    group_path = "/" + group_path
                if group_path in by_path and by_path[group_path]["id"] != group_id:
                    raise HierarchyProvisioningError(f"duplicate Keycloak group path: {group_path}")
                by_path[group_path] = {"id": group_id, "path": group_path}
                if group_id in visited:
                    continue
                visited.add(group_id)
                walk(group_path, group_id)

        walk("")
        return by_path

    def _client_uuid(self, client_id: str) -> str:
        rows = self._page("clients?" + urlencode({"clientId": client_id}))
        matches = [row for row in rows
                   if str(row.get("clientId") or "") == client_id]
        if len(matches) != 1 or not str(matches[0].get("id") or ""):
            raise HierarchyProvisioningError(
                f"Keycloak client is missing or ambiguous: {client_id}"
            )
        return str(matches[0]["id"])

    def ensure_group_claim_mapper(self, client_ids: list[str]) -> int:
        """Expose full Realm Group paths to Manager token introspection.

        Keycloak does not include group paths in introspection unless a mapper
        is attached to the client that issued the user's token. This mapper is
        deliberately scoped to the configured Manager login clients.
        """
        created = 0
        expected_config = {
            "claim.name": "groups", "full.path": "true",
            "id.token.claim": "true", "access.token.claim": "true",
            "userinfo.token.claim": "true", "introspection.token.claim": "true",
        }
        for client_id in sorted({str(value).strip() for value in client_ids if str(value).strip()}):
            client_uuid = self._client_uuid(client_id)
            endpoint = f"clients/{client_uuid}/protocol-mappers/models"
            rows = _rows(self.adapter._get(endpoint))
            matches = [row for row in rows
                       if str(row.get("name") or "") == _GROUP_CLAIM_MAPPER_NAME]
            if len(matches) > 1:
                raise HierarchyProvisioningError(
                    f"duplicate Keycloak group mappers on client: {client_id}"
                )
            if matches:
                mapper = matches[0]
                if (str(mapper.get("protocol") or "") != "openid-connect"
                        or str(mapper.get("protocolMapper") or "")
                        != "oidc-group-membership-mapper"
                        or {key: str((mapper.get("config") or {}).get(key, ""))
                            for key in expected_config} != expected_config):
                    raise HierarchyProvisioningError(
                        f"conflicting Keycloak group mapper on client: {client_id}"
                    )
                continue
            payload = {
                "name": _GROUP_CLAIM_MAPPER_NAME,
                "protocol": "openid-connect",
                "protocolMapper": "oidc-group-membership-mapper",
                "config": expected_config,
            }
            self.adapter._post(endpoint, payload)
            verified = _rows(self.adapter._get(endpoint))
            matches = [row for row in verified
                       if str(row.get("name") or "") == _GROUP_CLAIM_MAPPER_NAME]
            if len(matches) != 1:
                raise HierarchyProvisioningError(
                    f"Keycloak group mapper was not confirmed on client: {client_id}"
                )
            mapper = matches[0]
            if (str(mapper.get("protocolMapper") or "")
                    != "oidc-group-membership-mapper"
                    or {key: str((mapper.get("config") or {}).get(key, ""))
                        for key in expected_config} != expected_config):
                raise HierarchyProvisioningError(
                    f"Keycloak group mapper verification failed on client: {client_id}"
                )
            created += 1
        if not client_ids:
            raise HierarchyProvisioningError(
                "at least one Manager login client is required for group claims"
            )
        return created

    def _client_role_representations(
        self, client_id: str, roles: tuple[str, ...],
    ) -> tuple[str, list[dict[str, Any]]]:
        client_uuid = self._client_uuid(client_id)
        representations: list[dict[str, Any]] = []
        for role_name in roles:
            role = self.adapter._get(
                f"clients/{client_uuid}/roles/{role_name}"
            )
            if not isinstance(role, dict) or str(role.get("name") or "") != role_name:
                raise HierarchyProvisioningError(
                    f"required Keycloak role is missing: {client_id}:{role_name}"
                )
            representations.append(role)
        return client_uuid, representations

    def ensure_group_client_roles(
        self, group_ids: dict[str, str], group_path: str, client_id: str,
        roles: tuple[str, ...],
    ) -> int:
        group_id = group_ids.get(group_path)
        if not group_id:
            raise HierarchyProvisioningError(
                f"administrator group is absent from plan: {group_path}"
            )
        client_uuid, representations = self._client_role_representations(client_id, roles)
        endpoint = f"groups/{group_id}/role-mappings/clients/{client_uuid}"
        existing = _rows(self.adapter._get(endpoint))
        existing_names = {str(item.get("name") or "") for item in existing}
        dangerous = existing_names & _DANGEROUS_GROUP_ADMIN_ROLES
        if dangerous:
            raise HierarchyProvisioningError(
                f"scoped administrator group has broad Keycloak roles: {group_path}"
            )
        missing = [row for row in representations
                   if str(row.get("name") or "") not in existing_names]
        if missing:
            self.adapter._post(endpoint, missing)
        verified = {str(item.get("name") or "")
                    for item in _rows(self.adapter._get(endpoint))}
        if not set(roles) <= verified:
            raise HierarchyProvisioningError(
                f"Keycloak admin-console query roles did not verify: {group_path}"
            )
        return len(missing)

    def ensure_user_client_roles(
        self, username: str, client_id: str, roles: tuple[str, ...],
    ) -> int:
        client_uuid, representations = self._client_role_representations(client_id, roles)
        user_id = self.adapter.user_id(username)
        endpoint = f"users/{user_id}/role-mappings/clients/{client_uuid}"
        existing = _rows(self.adapter._get(endpoint))
        existing_names = {str(item.get("name") or "") for item in existing}
        missing = [row for row in representations
                   if str(row.get("name") or "") not in existing_names]
        if missing:
            self.adapter._post(endpoint, missing)
        verified = {str(item.get("name") or "")
                    for item in _rows(self.adapter._get(endpoint))}
        if not set(roles) <= verified:
            raise HierarchyProvisioningError(
                f"Keycloak administrator roles did not verify for user: {username}"
            )
        return len(missing)

    @staticmethod
    def _parent(path: str) -> tuple[str, str]:
        normalized = "/" + "/".join(part for part in str(path).split("/") if part)
        parent, separator, name = normalized.rpartition("/")
        if not separator or not name:
            raise ValueError(f"invalid Keycloak group path: {path}")
        return parent or "/", name

    def ensure_groups(self, paths: list[str]) -> tuple[dict[str, str], int]:
        normalized = sorted({"/" + "/".join(part for part in str(p).split("/") if part)
                             for p in paths}, key=lambda p: (p.count("/"), p))
        if any(path == "/" for path in normalized):
            raise ValueError("realm root is not a Keycloak group")
        groups = self._all_groups()
        created = 0
        for path in normalized:
            if path in groups:
                continue
            parent_path, name = self._parent(path)
            if parent_path != "/" and parent_path not in groups:
                raise HierarchyProvisioningError(f"missing planned parent group: {parent_path}")
            endpoint = (
                f"groups/{groups[parent_path]['id']}/children" if parent_path != "/"
                else "groups"
            )
            try:
                _, location = self.adapter._post(endpoint, {"name": name})
            except ValueError:
                # A concurrent/idempotent create is accepted only if the exact
                # deterministic path now exists; otherwise fail closed.
                groups = self._all_groups()
                if path not in groups:
                    raise HierarchyProvisioningError(f"Keycloak group create failed: {path}")
                continue
            created += 1
            group_id = str(location or "").rstrip("/").rsplit("/", 1)[-1]
            if group_id:
                groups[path] = {"id": group_id, "path": path}
            else:
                groups = self._all_groups()
            if path not in groups:
                raise HierarchyProvisioningError(f"Keycloak did not confirm created group: {path}")
        return {path: groups[path]["id"] for path in normalized}, created

    def _ensure_admin_permissions_client(self) -> str:
        rows = self._page("clients?" + urlencode({"clientId": "admin-permissions"}))
        matches = [row for row in rows
                   if str(row.get("clientId") or "") == "admin-permissions"]
        if len(matches) != 1 or not str(matches[0].get("id") or ""):
            raise HierarchyProvisioningError(
                "Keycloak FGAP v2 is not enabled; enable Admin Permissions before applying"
            )
        return str(matches[0]["id"])

    def enable_admin_permissions(self) -> str:
        """Enable Keycloak FGAP v2 and return its generated client UUID.

        The Admin REST update is a read/modify/write of the full realm
        representation so unrelated realm settings are preserved. This is
        called only from the explicit migration ``--apply`` path.
        """
        realm = self.adapter._get("")
        if not isinstance(realm, dict) or not realm:
            raise HierarchyProvisioningError(
                "Keycloak did not return the realm representation"
            )
        if realm.get("adminPermissionsEnabled") is not True:
            updated = dict(realm)
            updated["adminPermissionsEnabled"] = True
            try:
                self.adapter._put("", updated)
            except Exception as exc:
                raise HierarchyProvisioningError(
                    "Keycloak Admin Permissions could not be enabled"
                ) from exc
        # Keycloak creates this client when the realm setting is enabled.
        # Requiring it before group writes makes a partial/unsupported update
        # fail closed; rerunning the command is safe if the realm flag changed.
        return self._ensure_admin_permissions_client()

    def _named(self, endpoint: str, name: str, kind: str) -> dict[str, Any] | None:
        query = urlencode({"name": name})
        row = _exactly_one(_rows(self.adapter._get(f"{endpoint}?{query}")),
                           what=kind, name=name)
        # Search returns a generic PolicyRepresentation, whose config differs
        # from the typed group/scope representation used for parity checks.
        if row is not None and row.get("type") in {"group", "scope"} and row.get("id"):
            typed = self.adapter._get(
                f"{endpoint.removesuffix('/search')}/{row['type']}/{row['id']}"
            )
            if row["type"] == "scope":
                base = endpoint.split("/permission/", 1)[0] + f"/policy/{row['id']}"
                typed["resources"] = [r["name"] for r in self.adapter._get(base + "/resources")]
                typed["scopes"] = [r["name"] for r in self.adapter._get(base + "/scopes")]
                typed["policies"] = [r["name"] for r in self.adapter._get(base + "/associatedPolicies")]
            return typed
        return row

    def _ensure_group_policy(self, client_uuid: str, name: str, group_id: str) -> bool:
        base = f"clients/{client_uuid}/authz/resource-server/policy"
        existing = self._named(base + "/search", name, "group policy")
        expected_groups = {(group_id, False)}
        if existing is not None:
            groups = {
                (str(item.get("id") or ""), bool(item.get("extendChildren", False)))
                for item in existing.get("groups", []) if isinstance(item, dict)
            }
            if str(existing.get("logic") or "POSITIVE").upper() != "POSITIVE" or groups != expected_groups:
                raise HierarchyProvisioningError(f"conflicting Keycloak group policy: {name}")
            return False
        # Admin groups are already assigned by exact hierarchy. Extending a
        # group policy to children could silently make descendant admin groups
        # inherit the parent's authority, so keep this false explicitly.
        payload = {
            "name": name, "logic": "POSITIVE",
            "groups": [{"id": group_id, "extendChildren": False}],
        }
        try:
            self.adapter._post(base + "/group", payload)
        except ValueError:
            pass
        existing = self._named(base + "/search", name, "group policy")
        if existing is None:
            raise HierarchyProvisioningError(f"Keycloak group policy was not created: {name}")
        groups = {
            (str(item.get("id") or ""), bool(item.get("extendChildren", False)))
            for item in existing.get("groups", []) if isinstance(item, dict)
        }
        if str(existing.get("logic") or "POSITIVE").upper() != "POSITIVE" or groups != expected_groups:
            raise HierarchyProvisioningError(f"conflicting Keycloak group policy: {name}")
        return True

    def _ensure_group_permission(
        self, client_uuid: str, name: str, group_ids: list[str],
        scopes: list[str], policy_name: str,
    ) -> bool:
        normalized_ids = sorted(set(group_ids))
        normalized_scopes = sorted(set(scopes))
        if not normalized_ids or not normalized_scopes:
            return False
        if not set(normalized_scopes) <= _ALLOWED_GROUP_SCOPES:
            raise HierarchyProvisioningError(f"unsupported Keycloak group scopes: {name}")
        base = f"clients/{client_uuid}/authz/resource-server/permission"
        existing = self._named(base + "/search", name, "scope permission")
        if existing is not None:
            resources = sorted({str(item) for item in existing.get("resources", [])})
            existing_scopes = sorted({str(item) for item in existing.get("scopes", [])})
            policies = sorted({str(item) for item in existing.get("policies", [])})
            if (str(existing.get("resourceType") or "") != "Groups"
                    or resources != normalized_ids or existing_scopes != normalized_scopes
                    or policies != [policy_name]):
                raise HierarchyProvisioningError(f"conflicting Keycloak scope permission: {name}")
            return False
        payload = {
            "name": name, "resourceType": "Groups", "resources": normalized_ids,
            "scopes": normalized_scopes, "policies": [policy_name],
        }
        try:
            self.adapter._post(base + "/scope", payload)
        except ValueError:
            pass
        existing = self._named(base + "/search", name, "scope permission")
        if existing is None:
            raise HierarchyProvisioningError(f"Keycloak scope permission was not created: {name}")
        resources = sorted({str(item) for item in existing.get("resources", [])})
        existing_scopes = sorted({str(item) for item in existing.get("scopes", [])})
        policies = sorted({str(item) for item in existing.get("policies", [])})
        if (str(existing.get("resourceType") or "") != "Groups"
                or resources != normalized_ids or existing_scopes != normalized_scopes
                or policies != [policy_name]):
            raise HierarchyProvisioningError(f"conflicting Keycloak scope permission: {name}")
        return True

    def ensure_scoped_permissions(
        self, mappings: list[dict[str, Any]], group_ids: dict[str, str],
    ) -> dict[str, int]:
        if not mappings:
            return {"policies_created": 0, "permissions_created": 0}
        client_uuid = self._ensure_admin_permissions_client()
        policy_count = 0
        permission_count = 0
        for mapping in mappings:
            admin_path = str(mapping.get("administrator_group") or "")
            admin_id = group_ids.get(admin_path)
            if not admin_id:
                raise HierarchyProvisioningError("scoped administrator group is absent from plan")
            policy_name = f"tr-admin-group-{_digest(admin_path)}"
            policy_count += int(self._ensure_group_policy(client_uuid, policy_name, admin_id))
            for field, label in (
                ("managed_group_permissions", "managed"),
                ("assignable_administrator_group_permissions", "admin-groups"),
            ):
                entries = mapping.get(field) or []
                grouped: dict[tuple[str, ...], list[str]] = {}
                for entry in entries:
                    if not isinstance(entry, dict):
                        raise HierarchyProvisioningError("malformed scoped group permission plan")
                    path = str(entry.get("group_path") or "")
                    scopes = tuple(sorted({str(scope) for scope in entry.get("scopes", [])}))
                    if not path or path not in group_ids:
                        raise HierarchyProvisioningError(f"permission references unknown group path: {path}")
                    grouped.setdefault(scopes, []).append(group_ids[path])
                for scopes, ids in sorted(grouped.items()):
                    permission_name = f"tr-{label}-{_digest([admin_path, scopes, sorted(set(ids))])}"
                    permission_count += int(self._ensure_group_permission(
                        client_uuid, permission_name, ids, list(scopes), policy_name,
                    ))
        return {"policies_created": policy_count, "permissions_created": permission_count}

    def verify_memberships(self, memberships: list[dict[str, Any]]) -> None:
        for row in memberships:
            username = str(row.get("username") or "").strip()
            expected = {str(path) for path in row.get("group_paths", [])}
            user_id = self.adapter.user_id(username)
            actual_rows = _rows(self.adapter._get(f"users/{user_id}/groups"))
            actual = {str(item.get("path") or "") for item in actual_rows}
            if not expected <= actual:
                raise HierarchyProvisioningError(
                    f"Keycloak group membership did not verify for user: {username}"
                )


def apply_keycloak_hierarchy_plan(
    plan: dict[str, Any], adapter, *, roles_client_id: str,
    session_client_ids: list[str],
) -> dict[str, Any]:
    """Apply and verify one reviewed role/hierarchy plan; safe to rerun."""
    blockers = {key: plan.get(key) for key in _BLOCKING_PLAN_KEYS if plan.get(key)}
    if blockers:
        return {"applied": False, "blocked": blockers, "failures": []}
    tree = plan.get("realm_group_plan") or {}
    paths = tree.get("paths") or []
    memberships = tree.get("account_memberships") or []
    scoped = plan.get("scoped_admin_mappings") or []
    role_mappings = plan.get("mappings") or []
    if (scoped or role_mappings) and not roles_client_id:
        return {"applied": False, "blocked": {"roles_client_id": True}, "failures": []}
    if memberships and not session_client_ids:
        return {"applied": False, "blocked": {"session_client_ids": True}, "failures": []}

    provisioner = KeycloakHierarchyProvisioner(adapter)
    # Enable FGAP v2 before group writes. Keycloak creates the
    # ``admin-permissions`` client as part of enabling the realm setting.
    if scoped:
        provisioner.enable_admin_permissions()
    group_ids, groups_created = provisioner.ensure_groups(paths)
    fgap = provisioner.ensure_scoped_permissions(scoped, group_ids)
    group_mappers_created = provisioner.ensure_group_claim_mapper(session_client_ids) if memberships else 0
    memberships_added = 0
    for row in memberships:
        username = str(row.get("username") or "").strip()
        if not username:
            raise HierarchyProvisioningError("group membership plan has an empty username")
        user_id = adapter.user_id(username)
        existing_paths = {
            str(item.get("path") or "")
            for item in _rows(adapter._get(f"users/{user_id}/groups"))
        }
        for group_path in row.get("group_paths", []):
            group_id = group_ids.get(str(group_path))
            if not group_id:
                raise HierarchyProvisioningError(f"membership references unknown group: {group_path}")
            if str(group_path) not in existing_paths:
                adapter._put(f"users/{user_id}/groups/{group_id}", {})
                memberships_added += 1

    provisioner.verify_memberships(memberships)

    realm_admin_client_roles_added = 0
    for mapping in scoped:
        realm_admin_client_roles_added += provisioner.ensure_group_client_roles(
            group_ids,
            str(mapping.get("administrator_group") or ""),
            "realm-management",
            _GROUP_ADMIN_CLIENT_ROLES,
        )
    realm_admin_users_granted = 0
    for mapping in role_mappings:
        if "admin_console:manage" in set(mapping.get("client_roles") or ()):
            realm_admin_users_granted += provisioner.ensure_user_client_roles(
                str(mapping.get("username") or ""),
                "realm-management", ("realm-admin",),
            )

    # The older helper intentionally blocked while scoped policies were
    # pending. They are now created and verified above, so only this transient
    # planning marker is cleared in the in-memory copy before global role adds.
    role_plan = dict(plan)
    role_plan["scoped_authorization_pending"] = []
    from scripts.migrations.keycloak_roles import apply_role_mappings

    roles = apply_role_mappings(role_plan, adapter, roles_client_id)
    failures = roles.get("failures") or []
    return {
        "applied": not bool(failures or roles.get("blocked")),
        "blocked": roles.get("blocked") or {},
        "groups_created": groups_created,
        "memberships_verified": len(memberships),
        "memberships_applied_idempotently": memberships_added,
        "group_claim_mappers_created": group_mappers_created,
        "realm_management_query_roles_added": realm_admin_client_roles_added,
        "realm_admin_users_granted": realm_admin_users_granted,
        **fgap,
        "roles": roles,
        "failures": failures,
    }


__all__ = [
    "HierarchyProvisioningError", "KeycloakHierarchyProvisioner",
    "apply_keycloak_hierarchy_plan",
]
