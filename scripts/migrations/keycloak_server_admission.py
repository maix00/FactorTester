#!/usr/bin/env python3
"""Review, apply or undo Keycloak Manager admission configuration.

Default behavior is an offline-style read-only plan against Keycloak.  The
protected receipt records the prior group attributes and specific permissions;
it never contains client secrets.  No unrelated role, group or policy is
changed.  Keycloak REST is not transactional, so partial changes fail closed
and can be retried or rolled back using the receipt after drift checks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import quote, urlencode
import urllib.error
import urllib.request

from server.identity.realm_groups import organization_group_path
from server.identity.server_admission import manager_binding_group_path
from server.manager.domain.organization_scope import normalize_organization_id


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def _group(adapter, path):
    try:
        value = adapter._get("group-by-path/" + quote(path.lstrip("/"), safe="/"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    if not isinstance(value, dict) or value.get("path") != path or not value.get("id"):
        raise ValueError("Keycloak returned an invalid group")
    attributes = value.get("attributes") or {}
    if not isinstance(attributes, dict):
        raise ValueError("Keycloak group attributes are invalid")
    for key in ("tr_internal_manager_id", "tr_organization_id"):
        field = attributes.get(key)
        if field is not None and (not isinstance(field, list)
                                  or any(not isinstance(item, str) for item in field)):
            raise ValueError("Keycloak Manager binding is malformed")
    return {"id": str(value["id"]), "path": path, "attributes": attributes}


def _unique_client(adapter, client_id):
    rows = adapter._get("clients?" + urlencode({"clientId": client_id}))
    matches = [row for row in rows or [] if isinstance(row, dict)
               and row.get("clientId") == client_id and row.get("id")]
    if len(matches) != 1 or matches[0].get("enabled") is False:
        raise ValueError("Keycloak client is missing, disabled or ambiguous")
    return str(matches[0]["id"])


def _named(adapter, base, name, kind):
    value = adapter._get(base + "/search?" + urlencode({"name": name}))
    rows = value if isinstance(value, list) else ([value] if isinstance(value, dict) else [])
    matches = [row for row in rows if row.get("name") == name and row.get("id")]
    if len(matches) > 1:
        raise ValueError("Keycloak admission policy is ambiguous")
    if not matches:
        return None
    result = adapter._get(base.removesuffix("/search") + "/" + kind + "/" + str(matches[0]["id"]))
    if not isinstance(result, dict) or result.get("name") != name:
        raise ValueError("Keycloak admission policy could not be verified")
    return result


def _policy_names(server_id):
    suffix = hashlib.sha256(server_id.encode()).hexdigest()[:16]
    return "tr-manager-admission-user-" + suffix, "tr-manager-admission-client-view-" + suffix


def inspect_internal(adapter, *, server_id, organization_id):
    server_id = str(server_id or "").strip()
    if not server_id or len(server_id) > 256:
        raise ValueError("stable server ID is required")
    org = normalize_organization_id(organization_id)
    org_path = organization_group_path(org)
    manager_path = manager_binding_group_path(server_id)
    parent_path = manager_path.rpartition("/")[0]
    organization = _group(adapter, org_path)
    if organization is None:
        raise ValueError("reviewed organization group does not exist")
    manager = _group(adapter, manager_path)
    parent = _group(adapter, parent_path)
    conflicts = []
    if organization["attributes"].get("tr_internal_manager_id") not in (None, [], [server_id]):
        conflicts.append("organization_already_bound")
    if manager is not None and (
        manager["attributes"].get("tr_internal_manager_id") not in (None, [], [server_id])
        or manager["attributes"].get("tr_organization_id") not in (None, [], [org])
    ):
        conflicts.append("manager_already_bound")
    # Verify the one-to-one contract against every other existing binding.
    prefixes = ("/traderesearch/organizations/", "/traderesearch/internal-managers/")
    for row in adapter.group_representations():
        path = str(row.get("path") or "")
        if path in {org_path, manager_path}:
            continue
        prefix = next((p for p in prefixes if path.startswith(p)), "")
        if not prefix or "/" in path[len(prefix):]:
            continue
        other = _group(adapter, path)
        attrs = other["attributes"]
        if prefix == prefixes[0] and server_id in (attrs.get("tr_internal_manager_id") or []):
            conflicts.append("server_bound_to_another_organization")
        if prefix == prefixes[1] and org in (attrs.get("tr_organization_id") or []):
            conflicts.append("organization_bound_to_another_server")
    changes = []
    if parent is None:
        changes.append("create_manager_group_parent")
    if manager is None:
        changes.append("create_manager_binding_group")
    if organization["attributes"].get("tr_internal_manager_id") != [server_id]:
        changes.append("bind_organization_to_manager")
    if manager is None or manager["attributes"].get("tr_internal_manager_id") != [server_id] or manager["attributes"].get("tr_organization_id") != [org]:
        changes.append("bind_manager_to_organization")
    result = {"version": 1, "mode": "internal", "server_id": server_id,
              "realm": adapter.realm, "keycloak_base": adapter.base_url,
              "organization_id": org, "organization": organization,
              "manager": manager, "parent": parent, "changes": changes,
              "conflicts": sorted(set(conflicts))}
    result["sha256"] = _digest(result)
    return result


def inspect_public(adapter, *, server_id, directory_client_id, login_client_id, roles_client_id):
    server_id = str(server_id or "").strip()
    if not server_id or not directory_client_id or not login_client_id or roles_client_id != login_client_id:
        raise ValueError("Manager must inspect only its own login client")
    target = _unique_client(adapter, login_client_id)
    directory = _unique_client(adapter, directory_client_id)
    realm_management = _unique_client(adapter, "realm-management")
    permissions_client = _unique_client(adapter, "admin-permissions")
    user = adapter._get("clients/" + directory + "/service-account-user")
    if not isinstance(user, dict) or not user.get("id") or user.get("enabled") is not True:
        raise ValueError("Manager service account is missing")
    user_id = str(user["id"])
    role_path = "users/" + user_id + "/role-mappings/clients/" + realm_management
    direct = adapter._get(role_path)
    effective = adapter._get(role_path + "/composite")
    if not isinstance(direct, list) or not isinstance(effective, list):
        raise ValueError("Manager service roles are unavailable")
    direct_roles = sorted(str(row.get("name") or "") for row in direct)
    effective_roles = sorted(str(row.get("name") or "") for row in effective)
    base = "clients/" + permissions_client + "/authz/resource-server"
    policy_name, permission_name = _policy_names(server_id)
    policy = _named(adapter, base + "/policy", policy_name, "user")
    permission = _named(adapter, base + "/permission", permission_name, "scope")
    conflicts = []
    if "view-clients" in effective_roles or "manage-clients" in effective_roles:
        conflicts.append("unscoped_client_read_or_write_role")
    if policy is not None and (policy.get("users") != [user_id]
                               or policy.get("logic") != "POSITIVE"):
        conflicts.append("user_policy_conflict")
    if permission is not None:
        permission_id = str(permission["id"])
        root = base + "/policy/" + permission_id
        resources = sorted(str(row.get("name") or "") for row in adapter._get(root + "/resources"))
        scopes = sorted(str(row.get("name") or "") for row in adapter._get(root + "/scopes"))
        policies = sorted(str(row.get("name") or "") for row in adapter._get(root + "/associatedPolicies"))
        if (permission.get("resourceType") != "Clients"
                or permission.get("logic") != "POSITIVE"
                or permission.get("decisionStrategy") != "UNANIMOUS"
                or resources != [target]
                or scopes != ["view"] or policies != [policy_name] or policy is None):
            conflicts.append("client_permission_conflict")
    changes = []
    if "query-clients" not in effective_roles:
        changes.append("grant_query_clients")
    if policy is None:
        changes.append("create_service_account_policy")
    if permission is None:
        changes.append("create_single_client_view_permission")
    result = {"version": 1, "mode": "public", "server_id": server_id,
              "realm": adapter.realm, "keycloak_base": adapter.base_url,
              "directory_client_id": directory_client_id, "login_client_id": login_client_id,
              "roles_client_id": roles_client_id, "target_uuid": target,
              "directory_uuid": directory, "service_subject": user_id,
              "realm_management_uuid": realm_management, "permissions_uuid": permissions_client,
              "direct_roles": direct_roles, "effective_roles": effective_roles,
              "policy_name": policy_name, "permission_name": permission_name,
              "policy": policy, "permission": permission, "changes": changes,
              "conflicts": sorted(set(conflicts))}
    result["sha256"] = _digest(result)
    return result


def _inspect_again(adapter, plan):
    if plan["mode"] == "internal":
        return inspect_internal(adapter, server_id=plan["server_id"],
                                organization_id=plan["organization_id"])
    if plan["mode"] == "public":
        return inspect_public(adapter, server_id=plan["server_id"],
                              directory_client_id=plan["directory_client_id"],
                              login_client_id=plan["login_client_id"],
                              roles_client_id=plan["roles_client_id"])
    raise ValueError("invalid migration mode")


def _validate(plan, expected_sha256):
    body = dict(plan)
    actual = body.pop("sha256", "")
    if not actual or actual != expected_sha256 or actual != _digest(body):
        raise ValueError("reviewed plan digest is invalid")
    if plan.get("conflicts"):
        raise ValueError("Keycloak admission plan contains conflicts")


def _record(path, entry, *, create=False):
    flags = os.O_WRONLY | os.O_APPEND | (os.O_CREAT | os.O_EXCL if create else 0)
    fd = os.open(Path(path).expanduser(), flags, 0o600)
    with os.fdopen(fd, "a") as output:
        output.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
        output.flush()
        os.fsync(output.fileno())
    if create:
        fd = os.open(Path(path).expanduser().parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _set_attrs(adapter, path, expected, updates):
    current = _group(adapter, path)
    if current is None or current["attributes"] != expected:
        raise ValueError("Keycloak group changed since review")
    raw = adapter._get("groups/" + current["id"])
    attrs = dict(current["attributes"])
    attrs.update(updates)
    adapter._put("groups/" + current["id"], {**raw, "attributes": attrs})
    checked = _group(adapter, path)
    if checked is None or checked["attributes"] != attrs:
        raise RuntimeError("Keycloak group update did not verify")


def apply(adapter, plan, *, expected_sha256, receipt):
    _validate(plan, expected_sha256)
    if _inspect_again(adapter, plan) != plan:
        raise ValueError("Keycloak configuration changed after review")
    _record(receipt, {"plan": plan}, create=True)
    if plan["mode"] == "internal":
        from server.identity.keycloak_hierarchy_admin import KeycloakHierarchyProvisioner
        provisioner = KeycloakHierarchyProvisioner(adapter)
        org_path = plan["organization"]["path"]
        manager_path = manager_binding_group_path(plan["server_id"])
        parent_path = manager_path.rpartition("/")[0]
        for path in (parent_path, manager_path):
            if _group(adapter, path) is None:
                _record(receipt, {"intent": "create_group", "path": path})
                provisioner.ensure_groups([path])
                _record(receipt, {"created_group": path})
        if "bind_organization_to_manager" in plan["changes"]:
            _record(receipt, {"intent": "bind_organization"})
            _set_attrs(adapter, org_path, plan["organization"]["attributes"],
                       {"tr_internal_manager_id": [plan["server_id"]]})
            _record(receipt, {"completed": "bind_organization"})
        if "bind_manager_to_organization" in plan["changes"]:
            before = plan["manager"]["attributes"] if plan["manager"] else {}
            _record(receipt, {"intent": "bind_manager"})
            _set_attrs(adapter, manager_path, before, {
                "tr_internal_manager_id": [plan["server_id"]],
                "tr_organization_id": [plan["organization_id"]],
            })
            _record(receipt, {"completed": "bind_manager"})
    else:
        subject, realm = plan["service_subject"], plan["realm_management_uuid"]
        base = "clients/" + plan["permissions_uuid"] + "/authz/resource-server"
        if "grant_query_clients" in plan["changes"]:
            role = adapter._get("clients/" + realm + "/roles/query-clients")
            _record(receipt, {"intent": "grant_query_clients"})
            adapter._post("users/" + subject + "/role-mappings/clients/" + realm, [role])
            _record(receipt, {"completed": "grant_query_clients"})
        if "create_service_account_policy" in plan["changes"]:
            _record(receipt, {"intent": "create_policy"})
            adapter._post(base + "/policy/user", {"name": plan["policy_name"],
                          "logic": "POSITIVE", "users": [subject]})
            _record(receipt, {"completed": "create_policy"})
        if "create_single_client_view_permission" in plan["changes"]:
            _record(receipt, {"intent": "create_permission"})
            adapter._post(base + "/permission/scope", {"name": plan["permission_name"],
                          "resourceType": "Clients", "resources": [plan["target_uuid"]],
                          "scopes": ["view"], "policies": [plan["policy_name"]]})
            _record(receipt, {"completed": "create_permission"})
    verified = _inspect_again(adapter, plan)
    if verified["conflicts"] or verified["changes"]:
        raise RuntimeError("Keycloak admission configuration did not verify")
    _record(receipt, {"verified_sha256": verified["sha256"]})
    return {"status": "verified", "changes": len(plan["changes"]), "sha256": verified["sha256"]}


def _delete(adapter, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        f"{adapter.base_url}/admin/realms/{adapter.realm}/{path.lstrip('/')}",
        data=data, method="DELETE",
        headers={"Authorization": "Bearer " + adapter._token(), "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=adapter.timeout) as response:
        if response.status not in (200, 204):
            raise RuntimeError("Keycloak rollback was not accepted")


def _restore_attrs(adapter, current, before, intended):
    """Restore only reviewed fields and reject concurrent edits."""
    if current is None:
        raise ValueError("Keycloak group disappeared before rollback")
    attrs = dict(current["attributes"])
    for key, after in intended.items():
        prior = before.get(key)
        now = attrs.get(key)
        if now != prior and now != after:
            raise ValueError("Keycloak group binding changed after migration")
        if prior is None:
            attrs.pop(key, None)
        else:
            attrs[key] = prior
    unchanged = {key: value for key, value in current["attributes"].items() if key not in intended}
    if unchanged != {key: value for key, value in before.items() if key not in intended}:
        raise ValueError("other Keycloak group attributes changed after migration")
    return attrs


def rollback(adapter, plan, *, expected_sha256, record):
    """Undo only the exact additions from a protected migration receipt."""
    _validate(plan, expected_sha256)
    current = _inspect_again(adapter, plan)
    if current["conflicts"]:
        raise ValueError("Keycloak admission state conflicts with rollback")
    if plan["mode"] == "internal":
        org_path = plan["organization"]["path"]
        manager_path = manager_binding_group_path(plan["server_id"])
        org = _group(adapter, org_path)
        manager = _group(adapter, manager_path)
        if org is None or org["id"] != plan["organization"]["id"]:
            raise ValueError("organization group identity changed")
        org_attrs = _restore_attrs(adapter, org, plan["organization"]["attributes"],
                                   {"tr_internal_manager_id": [plan["server_id"]]})
        if plan["manager"] and (manager is None or manager["id"] != plan["manager"]["id"]):
            raise ValueError("Manager group identity changed")
        manager_before = plan["manager"]["attributes"] if plan["manager"] else {}
        manager_attrs = None if manager is None else _restore_attrs(adapter, manager, manager_before, {
            "tr_internal_manager_id": [plan["server_id"]],
            "tr_organization_id": [plan["organization_id"]],
        })
        # A newly created group can be removed only if no user or sub-group
        # appeared after migration. Check before any other rollback writes.
        if manager is not None and plan["manager"] is None:
            for endpoint in ("children", "members"):
                rows = adapter._get("groups/" + manager["id"] + "/" + endpoint + "?first=0&max=1")
                if not isinstance(rows, list) or rows:
                    raise ValueError("new Manager group is no longer empty")
        for path, selected, attrs in ((org_path, org, org_attrs), (manager_path, manager, manager_attrs)):
            if selected is None or attrs == selected["attributes"]:
                continue
            latest = _group(adapter, path)
            if latest != selected:
                raise ValueError("Keycloak group changed during rollback")
            raw = adapter._get("groups/" + selected["id"])
            adapter._put("groups/" + selected["id"], {**raw, "attributes": attrs})
            record({"restored_group": path})
        if manager is not None and plan["manager"] is None:
            latest = _group(adapter, manager_path)
            if latest is None or latest["id"] != manager["id"] or latest["attributes"] != manager_before:
                raise ValueError("new Manager group changed before deletion")
            for endpoint in ("children", "members"):
                rows = adapter._get("groups/" + manager["id"] + "/" + endpoint + "?first=0&max=1")
                if not isinstance(rows, list) or rows:
                    raise ValueError("new Manager group is no longer empty")
            _delete(adapter, "groups/" + manager["id"])
            record({"deleted_created_manager_group": True})
        # Keep an empty shared container group: another Manager may have
        # started using it, and it grants no access on its own.
    else:
        allowed_roles = sorted(set(plan["direct_roles"]) | ({"query-clients"}
                               if "grant_query_clients" in plan["changes"] else set()))
        if current["direct_roles"] not in (plan["direct_roles"], allowed_roles):
            raise ValueError("Manager service roles changed after migration")
        base = "clients/" + plan["permissions_uuid"] + "/authz/resource-server"
        if plan["permission"] is None and current["permission"] is not None:
            latest = _inspect_again(adapter, plan)
            if latest["conflicts"] or not latest["permission"] or latest["permission"]["id"] != current["permission"]["id"]:
                raise ValueError("Keycloak permission changed during rollback")
            _delete(adapter, base + "/permission/scope/" + str(current["permission"]["id"]))
            record({"deleted_created_permission": True})
        if plan["policy"] is None and current["policy"] is not None:
            latest = _inspect_again(adapter, plan)
            if latest["conflicts"] or not latest["policy"] or latest["policy"]["id"] != current["policy"]["id"]:
                raise ValueError("Keycloak policy changed during rollback")
            _delete(adapter, base + "/policy/" + str(current["policy"]["id"]))
            record({"deleted_created_policy": True})
        if "grant_query_clients" in plan["changes"] and "query-clients" in current["direct_roles"]:
            latest = _inspect_again(adapter, plan)
            if latest["conflicts"] or latest["direct_roles"] != current["direct_roles"]:
                raise ValueError("Manager service roles changed during rollback")
            role = adapter._get("clients/" + plan["realm_management_uuid"] + "/roles/query-clients")
            _delete(adapter, "users/" + plan["service_subject"] + "/role-mappings/clients/"
                    + plan["realm_management_uuid"], [role])
            record({"removed_query_clients": True})
    verified = _inspect_again(adapter, plan)
    if plan["mode"] == "internal":
        if (verified["conflicts"] or verified["organization"] != plan["organization"]
                or verified["manager"] != plan["manager"]):
            raise RuntimeError("Keycloak organization rollback did not verify")
    elif verified != plan:
        raise RuntimeError("Keycloak client-permission rollback did not verify")
    record({"verified": True})
    return {"status": "rolled_back"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("internal", "public"), required=True)
    parser.add_argument("--server-id", required=True)
    parser.add_argument("--organization-id", default="")
    parser.add_argument("--directory-client-id", default="")
    parser.add_argument("--login-client-id", default="")
    parser.add_argument("--roles-client-id", default="")
    parser.add_argument("--output", help="new protected plan path")
    parser.add_argument("--apply-plan", help="protected reviewed plan; default is read-only")
    parser.add_argument("--rollback-receipt", help="protected receipt created by apply")
    parser.add_argument("--expected-sha256", default="")
    parser.add_argument("--receipt", default="")
    args = parser.parse_args(argv)
    from server.identity.federation_identity_sync import manager_keycloak_admin_adapter
    adapter = manager_keycloak_admin_adapter()
    if args.apply_plan and args.rollback_receipt:
        parser.error("choose apply or rollback")
    if args.rollback_receipt:
        with Path(args.rollback_receipt).expanduser().open() as stream:
            plan = json.loads(stream.readline())["plan"]
        if plan.get("mode") != args.mode or plan.get("server_id") != args.server_id:
            parser.error("receipt does not match requested server and mode")
        result = rollback(adapter, plan, expected_sha256=args.expected_sha256,
                          record=lambda event: _record(args.rollback_receipt, {"rollback": event}))
    elif args.apply_plan:
        if not args.receipt:
            parser.error("--receipt is required when applying")
        plan = json.loads(Path(args.apply_plan).read_text())
        if plan.get("mode") != args.mode or plan.get("server_id") != args.server_id:
            parser.error("plan does not match requested server and mode")
        result = apply(adapter, plan, expected_sha256=args.expected_sha256, receipt=args.receipt)
    else:
        if not args.output:
            parser.error("--output is required for a read-only plan")
        if args.mode == "internal":
            plan = inspect_internal(adapter, server_id=args.server_id, organization_id=args.organization_id)
        else:
            plan = inspect_public(adapter, server_id=args.server_id,
                                  directory_client_id=args.directory_client_id,
                                  login_client_id=args.login_client_id,
                                  roles_client_id=args.roles_client_id)
        _record(args.output, plan, create=True)
        result = {"status": "blocked" if plan["conflicts"] else "planned",
                  "changes": plan["changes"], "conflicts": plan["conflicts"], "sha256": plan["sha256"]}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 2 if result["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
