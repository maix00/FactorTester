"""Stable TradeResearch Keycloak Realm Group path construction."""

from __future__ import annotations

import hashlib
import re


GROUP_ROOT = "/traderesearch"


def component(kind: str, value: str) -> str:
    """Encode a legacy directory key as a stable, collision-resistant path part."""
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(f"{kind} id is required")
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", raw).strip("-_").lower()[:32]
    slug = slug or "id"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"{kind}-{slug}-{digest}"


def organization_group_path(organization_id: str) -> str:
    return f"{GROUP_ROOT}/organizations/{component('org', organization_id)}"


def level_group_path(organization_id: str, level_id: str) -> str:
    return f"{organization_group_path(organization_id)}/levels/{component('level', level_id)}"


def organization_admin_group_path(organization_id: str) -> str:
    return (
        f"{GROUP_ROOT}/admin-scopes/organizations/{component('org', organization_id)}/"
        "organization-admins"
    )


def level_admin_group_path(organization_id: str, level_id: str) -> str:
    return (
        f"{GROUP_ROOT}/admin-scopes/organizations/{component('org', organization_id)}/"
        f"levels/{component('level', level_id)}-administrators"
    )


def administrative_group_role(groups: tuple[str, ...] | list[str]) -> str:
    """Project only the two exact delegated-admin group shapes to UI roles.

    These labels are informational. Authorization for Keycloak-managed
    resources must still be decided by Keycloak FGAP/Authorization Services.
    """
    for path in groups:
        parts = str(path or "").strip("/").split("/")
        if (len(parts) == 5 and parts[:2] == ["traderesearch", "admin-scopes"]
                and parts[2] == "organizations" and parts[3]
                and parts[4] == "organization-admins"):
            return "org_admin"
    for path in groups:
        parts = str(path or "").strip("/").split("/")
        if (len(parts) == 6 and parts[:2] == ["traderesearch", "admin-scopes"]
                and parts[2] == "organizations" and parts[3]
                and parts[4] == "levels" and parts[5].endswith("-administrators")
                and parts[5] != "-administrators"):
            return "level_admin"
    return "user"


def managed_member_group_paths(groups: object) -> set[str]:
    """Return the member-group roots governed by exact delegated-admin claims.

    Organization administrators manage that organization's full nested group
    tree. Level administrators manage their level subtree, including child
    levels. The result is derived only from normalized, verified token claims.
    """
    if not isinstance(groups, (tuple, list, set, frozenset)):
        return set()
    result: set[str] = set()
    for raw in groups:
        parts = str(raw or "").strip("/").split("/")
        if (
            len(parts) == 5
            and parts[:3] == ["traderesearch", "admin-scopes", "organizations"]
            and parts[3]
            and parts[4] == "organization-admins"
        ):
            result.add(f"/traderesearch/organizations/{parts[3]}")
        elif (
            len(parts) == 6
            and parts[:3] == ["traderesearch", "admin-scopes", "organizations"]
            and parts[3]
            and parts[4] == "levels"
            and parts[5].endswith("-administrators")
            and parts[5] != "-administrators"
        ):
            level = parts[5][:-len("-administrators")]
            result.add(
                f"/traderesearch/organizations/{parts[3]}/levels/{level}"
            )
    return result


def normalize_group_claim(value: object) -> tuple[str, ...] | None:
    """Validate a Keycloak group-path claim; ``None`` means malformed."""
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)) or len(value) > 2048:
        return None
    paths: set[str] = set()
    for raw in value:
        if not isinstance(raw, str) or len(raw) > 512:
            return None
        path = raw.strip()
        if (not path.startswith("/") or path == "/" or "//" in path
                or any(ord(char) < 32 for char in path)):
            return None
        if path != GROUP_ROOT and not path.startswith(GROUP_ROOT + "/"):
            return None
        paths.add(path.rstrip("/"))
    return tuple(sorted(paths))

