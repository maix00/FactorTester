"""Build a reviewable Keycloak Realm Group plan from legacy org/level data.

Realm Groups are used here because Keycloak Fine-Grained Admin Permissions do
not currently accept Organization Groups as policy subjects. This module only
plans stable paths; it does not create groups or policies in a live realm.
"""

from __future__ import annotations

from server.identity.realm_groups import (
    GROUP_ROOT,
    component as _component,
    level_group_path,
    organization_admin_group_path,
    organization_group_path,
    level_admin_group_path,
)


SCOPED_GROUP_SCOPES = ["view", "view-members", "manage-members", "manage-membership"]


def _group_permission_plan(paths: list[str]) -> list[dict[str, object]]:
    return [
        {"group_path": path, "scopes": list(SCOPED_GROUP_SCOPES)}
        for path in sorted(set(paths))
    ]


def complete_group_tree(paths: list[str] | set[str]) -> list[str]:
    """Return every parent and leaf needed to create the planned Realm Groups.

    Keycloak's Groups Admin API creates one child at a time, so a plan that
    lists only leaf paths is not directly executable and can leave partial
    trees on rerun. This expands the small migration plan (not request-time
    authorization) into a deterministic parent-before-child path set.
    """
    result = {GROUP_ROOT}
    for raw_path in paths:
        segments = [segment for segment in str(raw_path or "").split("/") if segment]
        current = ""
        for segment in segments:
            current += f"/{segment}"
            result.add(current)
    return sorted(result, key=lambda path: (path.count("/"), path))


def _admin_scope_group(org_id: str, level_id: str = "") -> str:
    if not level_id:
        return organization_admin_group_path(org_id)
    return level_admin_group_path(org_id, level_id)


def hierarchy_group_paths(
    organizations: list[dict], levels: list[dict],
) -> tuple[dict[str, str], list[dict[str, str]]]:
    """Return level-id -> realm-group-path and structural errors.

    Paths are nested by the frozen parent links, not by display names. Duplicate
    IDs, missing organizations/parents, cross-organization parents, and cycles
    are reported instead of being guessed around.
    """
    errors: list[dict[str, str]] = []
    org_ids: set[str] = set()
    for item in organizations:
        if not isinstance(item, dict):
            continue
        org_id = str(item.get("id") or "").strip()
        if not org_id:
            errors.append({"kind": "organization", "id": "", "reason": "missing_id"})
        elif org_id in org_ids:
            errors.append({"kind": "organization", "id": org_id, "reason": "duplicate_id"})
        else:
            org_ids.add(org_id)
    by_id: dict[str, dict] = {}
    for item in levels:
        if not isinstance(item, dict):
            continue
        level_id = str(item.get("id") or "").strip()
        if not level_id:
            errors.append({"kind": "level", "id": "", "reason": "missing_id"})
            continue
        if level_id in by_id:
            errors.append({"kind": "level", "id": level_id, "reason": "duplicate_id"})
            continue
        by_id[level_id] = item

    paths: dict[str, str] = {}
    visiting: set[str] = set()

    def path_for(level_id: str) -> str | None:
        if level_id in paths:
            return paths[level_id]
        item = by_id.get(level_id)
        if item is None:
            errors.append({"kind": "level", "id": level_id, "reason": "missing_level"})
            return None
        if level_id in visiting:
            errors.append({"kind": "level", "id": level_id, "reason": "cycle"})
            return None
        visiting.add(level_id)
        org_id = str(item.get("organization_id") or "").strip()
        if not org_id or org_id not in org_ids:
            errors.append({"kind": "level", "id": level_id, "reason": "missing_organization"})
            visiting.remove(level_id)
            return None
        org_path = organization_group_path(org_id)
        parent_id = str(item.get("parent_level_id") or "").strip()
        if parent_id:
            parent = by_id.get(parent_id)
            if parent is None:
                errors.append({"kind": "level", "id": level_id, "reason": "missing_parent"})
                visiting.remove(level_id)
                return None
            if str(parent.get("organization_id") or "").strip() != org_id:
                errors.append({"kind": "level", "id": level_id, "reason": "cross_organization_parent"})
                visiting.remove(level_id)
                return None
            parent_path = path_for(parent_id)
            if parent_path is None:
                visiting.remove(level_id)
                return None
            result = f"{parent_path}/{_component('level', level_id)}"
        else:
            result = level_group_path(org_id, level_id)
        visiting.remove(level_id)
        paths[level_id] = result
        return result

    for level_id in sorted(by_id):
        path_for(level_id)
    return paths, sorted(errors, key=lambda item: (item["kind"], item["id"], item["reason"]))


def scoped_admin_mapping(
    account: dict, organizations: list[dict], levels: list[dict],
    level_paths: dict[str, str],
) -> tuple[dict | None, dict[str, str] | None]:
    """Resolve one scoped legacy admin to its Keycloak groups and subtree."""
    username = str(account.get("username") or "").strip()
    role = str(account.get("role") or "user").strip()
    org_id = str(account.get("organization_id") or "").strip()
    if not org_id or not any(
        isinstance(item, dict) and str(item.get("id") or "").strip() == org_id
        for item in organizations
    ):
        return None, {"username": username, "reason": "missing_organization"}
    if role == "org_admin":
        roots = [
            str(item.get("id") or "") for item in levels
            if isinstance(item, dict)
            and str(item.get("organization_id") or "").strip() == org_id
            and not str(item.get("parent_level_id") or "").strip()
        ]
        org_level_ids = {
            str(level.get("id") or "").strip()
            for level in levels
            if isinstance(level, dict)
            and str(level.get("organization_id") or "").strip() == org_id
            and str(level.get("id") or "").strip()
        }
        managed = sorted(level_paths[item] for item in org_level_ids if item in level_paths)
        roots_managed = [level_paths[item] for item in sorted(roots) if item in level_paths]
        if not roots_managed:
            return None, {"username": username, "reason": "missing_level_roots"}
        admin_group = _admin_scope_group(org_id)
        assignable_admin_groups = [
            _admin_scope_group(org_id, str(item.get("id") or "").strip())
            for item in levels
            if isinstance(item, dict)
            and str(item.get("organization_id") or "").strip() == org_id
            and str(item.get("id") or "").strip()
        ]
        assignable_admin_group_permissions = _group_permission_plan(assignable_admin_groups)
        managed_group_permissions = _group_permission_plan(managed)
        return {
            "username": username, "legacy_role": role,
            "organization_id": org_id, "level_id": "",
            "administrator_group": admin_group,
            "managed_group_roots": roots_managed,
            "managed_group_paths": managed,
            "managed_group_permissions": managed_group_permissions,
            "assignable_administrator_groups": sorted(assignable_admin_groups),
            "assignable_administrator_group_permissions": assignable_admin_group_permissions,
            "group_permission_scopes": list(SCOPED_GROUP_SCOPES),
            "user_permission_scopes": ["manage-group-membership"],
            "subtree": True,
            "permission_model": "realm_group_fgaps",
        }, None

    level_id = str(account.get("level_id") or "").strip() or f"{org_id}__ROOT"
    level = next((item for item in levels if isinstance(item, dict)
                  and str(item.get("id") or "").strip() == level_id), None)
    if not level_id or level is None or level_id not in level_paths:
        return None, {"username": username, "reason": "missing_level"}
    if str(level.get("organization_id") or "").strip() != org_id:
        return None, {"username": username, "reason": "level_organization_mismatch"}

    children: dict[str, list[str]] = {}
    for item in levels:
        if not isinstance(item, dict) or str(item.get("organization_id") or "").strip() != org_id:
            continue
        child_id = str(item.get("id") or "").strip()
        if child_id:
            children.setdefault(str(item.get("parent_level_id") or "").strip(), []).append(child_id)
    descendants: set[str] = set()
    stack = [level_id]
    while stack:
        current = stack.pop()
        if current in descendants:
            continue
        descendants.add(current)
        stack.extend(children.get(current, ()))
    admin_group = _admin_scope_group(org_id, level_id)
    assignable_admin_groups = [
        _admin_scope_group(org_id, item)
        for item in sorted(descendants)
        if item in level_paths
    ]
    managed_paths = [level_paths[item] for item in sorted(descendants) if item in level_paths]
    assignable_admin_group_permissions = _group_permission_plan(assignable_admin_groups)
    return {
        "username": username, "legacy_role": role,
        "organization_id": org_id, "level_id": level_id,
        "administrator_group": admin_group,
        "managed_group_roots": [level_paths[level_id]],
        "managed_group_paths": managed_paths,
        "managed_group_permissions": _group_permission_plan(managed_paths),
        "assignable_administrator_groups": sorted(assignable_admin_groups),
        "assignable_administrator_group_permissions": assignable_admin_group_permissions,
        "group_permission_scopes": list(SCOPED_GROUP_SCOPES),
        "user_permission_scopes": ["manage-group-membership"],
        "subtree": True,
        "permission_model": "realm_group_fgaps",
    }, None


def membership_group(account: dict, level_paths: dict[str, str]) -> str | None:
    organization_id = str(account.get("organization_id") or "").strip()
    if not organization_id:
        return None
    level_id = str(account.get("level_id") or "").strip() or f"{organization_id}__ROOT"
    return level_paths.get(level_id) if level_id else None
