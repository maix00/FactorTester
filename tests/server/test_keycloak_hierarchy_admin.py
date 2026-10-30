from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from scripts.migrations.keycloak_roles import role_mappings_for_accounts
from server.identity.keycloak_hierarchy_admin import (
    HierarchyProvisioningError,
    KeycloakHierarchyProvisioner,
    apply_keycloak_hierarchy_plan,
)


ORGS = [{"id": "default"}, {"id": "org-a"}]
LEVELS = [
    {"id": "default__ROOT", "organization_id": "default"},
    {"id": "org-a__ROOT", "organization_id": "org-a"},
    {"id": "north", "organization_id": "org-a", "parent_level_id": "org-a__ROOT"},
    {"id": "team-1", "organization_id": "org-a", "parent_level_id": "north"},
]


class FakeKeycloak:
    def __init__(self, *, admin_permissions=True, can_enable_admin_permissions=True):
        self.admin_permissions = admin_permissions
        self.can_enable_admin_permissions = can_enable_admin_permissions
        self.groups = {}
        self.client_ids = {
            "manager-api": "role-client-uuid",
            "manager-web": "web-client-uuid",
            "realm-management": "realm-management-client-uuid",
        }
        self.group_mappers = {client_uuid: [] for client_uuid in self.client_ids.values()}
        self.group_roles = {}
        self.user_client_roles = {}
        self.memberships = {"super": set(), "org-admin": set(), "level-admin": set(), "person": set()}
        self.policies = {}
        self.permissions = {}
        self.roles = {name: set() for name in self.memberships}
        self._counter = 0
        self.role_client = "role-client-uuid"

    @staticmethod
    def _query(path):
        return parse_qs(urlsplit(path).query)

    def _group_rows(self, parent_path=""):
        rows = []
        for path, group_id in self.groups.items():
            parent, _, _name = path.rpartition("/")
            if parent == parent_path:
                rows.append({"id": group_id, "name": path.rsplit("/", 1)[-1], "path": path})
        return rows

    def _get(self, path):
        if path == "":
            return {
                "realm": "research",
                "adminPermissionsEnabled": self.admin_permissions,
                "registrationAllowed": False,
            }
        if path.startswith("clients?"):
            query = self._query(path)
            client_id = query.get("clientId", [""])[0]
            if client_id == "admin-permissions" and self.admin_permissions:
                return [{"id": "admin-permissions-uuid", "clientId": client_id}]
            return ([{"id": self.client_ids[client_id], "clientId": client_id}]
                    if client_id in self.client_ids else [])
        if path.startswith("clients/") and path.endswith("/protocol-mappers/models"):
            client_uuid = path.split("/", 2)[1]
            return list(self.group_mappers.get(client_uuid, []))
        if path.startswith("groups?"):
            return self._group_rows("")
        if path.startswith("groups/") and path.endswith("/children?first=0&max=500"):
            group_id = path.split("/", 2)[1]
            parent = next((p for p, gid in self.groups.items() if gid == group_id), None)
            return self._group_rows(parent or "")
        if path.startswith("users?"):
            query = self._query(path)
            username = query.get("username", [""])[0]
            return [{"id": f"u-{username}", "username": username}] if username in self.memberships else []
        if path.endswith("/groups") and path.startswith("users/"):
            user_id = path.split("/", 2)[1]
            username = user_id.removeprefix("u-")
            return [{"id": self.groups[p], "path": p} for p in sorted(self.memberships[username])]
        if "/authz/resource-server/policy/search?" in path:
            name = self._query(path).get("name", [""])[0]
            return [self.policies[name]] if name in self.policies else []
        if "/authz/resource-server/permission/search?" in path:
            name = self._query(path).get("name", [""])[0]
            return [self.permissions[name]] if name in self.permissions else []
        if "/role-mappings/clients/" in path:
            client_uuid = path.rsplit("/", 1)[-1]
            if path.startswith("groups/"):
                group_id = path.split("/", 2)[1]
                return [{"name": role} for role in self.group_roles.get(group_id, set())]
            username = path.split("/", 3)[1].removeprefix("u-")
            roles = self.user_client_roles.get((username, client_uuid), set())
            if client_uuid == self.role_client:
                roles = self.roles[username]
            return [{"name": role} for role in roles]
        if "/roles/" in path:
            role = path.rsplit("/", 1)[-1]
            return {"id": "r-" + role, "name": role}
        raise AssertionError(f"unexpected GET {path}")

    def _post(self, path, payload):
        if path.endswith("/protocol-mappers/models"):
            client_uuid = path.split("/", 2)[1]
            self.group_mappers[client_uuid].append(dict(payload))
            return 201, ""
        if path.startswith("users/") and "/role-mappings/clients/" in path:
            username = path.split("/", 2)[1].removeprefix("u-")
            client_uuid = path.rsplit("/", 1)[-1]
            self.user_client_roles.setdefault((username, client_uuid), set()).update(
                item["name"] for item in payload
            )
            return 204, ""
        if path.startswith("groups/") and "/role-mappings/clients/" in path:
            group_id = path.split("/", 2)[1]
            self.group_roles.setdefault(group_id, set()).update(item["name"] for item in payload)
            return 204, ""
        if path == "groups":
            group_path = "/" + payload["name"]
        elif path.endswith("/children"):
            group_id = path.split("/", 2)[1]
            parent = next(p for p, gid in self.groups.items() if gid == group_id)
            group_path = parent + "/" + payload["name"]
        elif path.endswith("/policy/group"):
            self.policies[payload["name"]] = dict(payload)
            return 201, ""
        elif path.endswith("/permission/scope"):
            self.permissions[payload["name"]] = dict(payload)
            return 201, ""
        else:
            raise AssertionError(f"unexpected POST {path}")
        if group_path in self.groups:
            raise ValueError("conflict")
        self._counter += 1
        group_id = f"g{self._counter}"
        self.groups[group_path] = group_id
        return 201, f"https://id.example/admin/groups/{group_id}"

    def _put(self, path, payload):
        if path == "":
            if not self.can_enable_admin_permissions:
                raise PermissionError("realm update denied")
            assert payload["registrationAllowed"] is False
            self.admin_permissions = bool(payload["adminPermissionsEnabled"])
            return 204
        if "/groups/" in path and path.startswith("users/"):
            user_id, group_id = path.split("/", 3)[1], path.rsplit("/", 1)[1]
            username = user_id.removeprefix("u-")
            group_path = next(p for p, gid in self.groups.items() if gid == group_id)
            self.memberships[username].add(group_path)
            return 204
        if "/role-mappings/clients/" in path:
            username = path.split("/", 3)[1].removeprefix("u-")
            self.roles[username].update(item["name"] for item in payload)
            return 204
        raise AssertionError(f"unexpected PUT {path}")

    def user_id(self, username):
        if username not in self.memberships:
            raise LookupError(username)
        return f"u-{username}"

    def add_client_roles(self, username, client_id, role_names):
        assert client_id == "manager-api"
        missing = sorted(set(role_names) - self.roles[username])
        self.roles[username].update(missing)
        return missing


def _plan():
    return role_mappings_for_accounts([
        {"username": "super", "role": "super_admin", "organization_id": "org-a"},
        {"username": "org-admin", "role": "org_admin", "organization_id": "org-a"},
        {"username": "level-admin", "role": "level_admin", "organization_id": "org-a",
         "level_id": "north"},
        {"username": "person", "role": "user", "organization_id": "org-a", "level_id": "team-1"},
    ], ORGS, LEVELS)


def test_applies_groups_memberships_and_scoped_admin_permissions_idempotently():
    plan = _plan()
    adapter = FakeKeycloak()

    first = apply_keycloak_hierarchy_plan(
        plan, adapter, roles_client_id="manager-api", session_client_ids=["manager-web"],
    )
    second = apply_keycloak_hierarchy_plan(
        plan, adapter, roles_client_id="manager-api", session_client_ids=["manager-web"],
    )

    assert first["applied"] is True
    assert first["groups_created"] == len(plan["realm_group_plan"]["paths"])
    assert first["policies_created"] == 2
    assert first["permissions_created"] == 4
    assert first["memberships_verified"] == 4
    assert adapter.roles["super"] == {"admin_console:manage", "admin_console:read"}
    assert adapter.user_client_roles[("super", "realm-management-client-uuid")] == {"realm-admin"}
    assert adapter.memberships["person"] == {
        plan["realm_group_plan"]["level_paths"]["team-1"],
    }
    assert second["applied"] is True
    assert second["groups_created"] == 0
    assert second["policies_created"] == 0
    assert second["permissions_created"] == 0
    assert second["memberships_applied_idempotently"] == 0
    assert second["roles"]["applied"][0]["assigned_roles"] == []

    # The policy includes only its scoped administrator group. Its target
    # permissions enumerate exactly the planned descendant resources.
    scoped = {row["username"]: row for row in plan["scoped_admin_mappings"]}
    for username, mapping in scoped.items():
        admin_group_id = adapter.groups[mapping["administrator_group"]]
        assert any(
            policy["groups"] == [
                {"id": admin_group_id, "extendChildren": False},
            ]
            for policy in adapter.policies.values()
        )
        target_paths = set(mapping["managed_group_paths"])
        if target_paths:
            expected_ids = {adapter.groups[path] for path in target_paths}
            assert any(set(permission["resources"]) == expected_ids
                       for permission in adapter.permissions.values())


def test_enables_keycloak_admin_permissions_before_provisioning_groups():
    adapter = FakeKeycloak(admin_permissions=False)
    plan = _plan()

    result = apply_keycloak_hierarchy_plan(
        plan, adapter, roles_client_id="manager-api", session_client_ids=["manager-web"],
    )

    assert result["applied"] is True
    assert adapter.admin_permissions is True
    assert adapter.groups


def test_cannot_enable_keycloak_admin_permissions_before_group_writes():
    adapter = FakeKeycloak(
        admin_permissions=False,
        can_enable_admin_permissions=False,
    )
    plan = _plan()

    with pytest.raises(HierarchyProvisioningError, match="could not be enabled"):
        apply_keycloak_hierarchy_plan(
            plan, adapter, roles_client_id="manager-api", session_client_ids=["manager-web"],
        )

    assert adapter.groups == {}
    assert adapter.memberships["org-admin"] == set()


def test_rejects_a_conflicting_named_permission_without_overwriting_it():
    adapter = FakeKeycloak()
    plan = _plan()
    first = apply_keycloak_hierarchy_plan(
        plan, adapter, roles_client_id="manager-api", session_client_ids=["manager-web"],
    )
    assert first["applied"]
    permission = next(iter(adapter.permissions.values()))
    permission["resources"] = ["unrelated-group"]

    with pytest.raises(HierarchyProvisioningError, match="conflicting Keycloak scope permission"):
        apply_keycloak_hierarchy_plan(
            plan, adapter, roles_client_id="manager-api", session_client_ids=["manager-web"],
        )

    assert permission["resources"] == ["unrelated-group"]


def test_group_pagination_builds_paths_without_loading_members_per_group():
    adapter = FakeKeycloak()
    adapter.groups = {"/traderesearch": "g1", "/traderesearch/organizations": "g2"}
    index = KeycloakHierarchyProvisioner(adapter)._all_groups()

    assert index["/traderesearch"]["id"] == "g1"
    assert index["/traderesearch/organizations"]["id"] == "g2"


def test_real_keycloak_generic_search_loads_typed_policy_and_scope_associations():
    class API:
        def _get(self, path):
            if '/search?' in path:
                return {'id': 'p', 'name': 'grant', 'type': 'scope', 'resourceType': 'Groups'}
            if path.endswith('/scope/p'):
                return {'id': 'p', 'name': 'grant', 'resourceType': 'Groups'}
            if path.endswith('/resources'):
                return [{'name': 'group-id', '_id': 'resource-id'}]
            if path.endswith('/scopes'):
                return [{'name': 'view-members', 'id': 'scope-id'}]
            if path.endswith('/associatedPolicies'):
                return [{'name': 'admin-group-policy', 'id': 'policy-id'}]
            raise AssertionError(path)
    row = KeycloakHierarchyProvisioner(API())._named(
        'clients/c/authz/resource-server/permission/search', 'grant', 'scope permission')
    assert row['resources'] == ['group-id']
    assert row['scopes'] == ['view-members']
    assert row['policies'] == ['admin-group-policy']
