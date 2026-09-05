"""Server registry for explicitly synchronized immutable factor sets."""

from __future__ import annotations

from typing import Any

from server.services.factor_subject_descriptors import (
    validate_factor_subject_descriptors,
)
from tools.data.account_manage import (
    delete_factor_set,
    get_factor_set,
    list_factor_sets,
    save_factor_set,
)
from tools.factors.factor_set_identity import freeze_factor_set_identity, require_frozen_factor_set
from tools.factors.formula_identity import require_frozen_factor


def register_factor_set(
    username: str, descriptor: dict[str, Any],
) -> dict[str, Any]:
    validated = validate_factor_subject_descriptors([descriptor])[0]
    value = {
        **descriptor["manifest"],
        "authority": validated["authority"],
        "owner_username": username,
    }
    return _summary(save_factor_set(username, value))


def author_factor_set(
    username: str,
    definition: dict[str, Any],
    *,
    persist: bool,
    replace_target_ref: str = "",
) -> dict[str, Any]:
    """Freeze one Web-authored set without trusting a client-supplied owner."""
    set_id = str(definition.get("set_id") or "").strip()
    alias = str(
        definition.get("alias") or definition.get("title_zh") or ""
    ).strip()
    raw_members = definition.get("members")
    if not set_id or not alias:
        raise ValueError("factor-set set_id and alias are required")
    if not isinstance(raw_members, list) or not raw_members:
        raise ValueError("factor-set members must be a non-empty list")
    members = [require_frozen_factor(member) for member in raw_members]
    value = freeze_factor_set_identity(
        owner_ref=f"principal:{username}",
        set_id=set_id,
        alias=alias,
        members=members,
    )
    description = str(definition.get("description") or "").strip()
    if description:
        value["description"] = description
    value["authority"] = "server_web"
    value["owner_username"] = username
    if persist:
        value = save_factor_set(username, value)
        old_ref = str(replace_target_ref or "").strip()
        if old_ref and old_ref != value["ref"]:
            delete_factor_set(username, old_ref)
    return {
        **_summary(value),
        "manifest": _manifest(value),
        "related_references": [
            {
                "relation": "集合成员",
                "kind": "factor",
                "target_ref": member["ref"],
                "label": member["alias"],
                "data": member,
            }
            for member in value["identity"]["members"]
        ],
        "temporary": not persist,
    }


def factor_set_catalog(username: str, query: str = "") -> list[dict[str, Any]]:
    needle = query.strip().casefold()
    values = list_factor_sets(username)
    if needle:
        values = [
            value for value in values
            if needle in " ".join([
                str((value.get("identity") or {}).get("set_id") or ""),
                str(value.get("alias") or ""),
                str(value.get("description") or ""),
                str(value.get("owner_ref") or ""),
            ]).casefold()
        ]
    return [_summary(value) for value in values]


def factor_set_detail(
    username: str, target_ref: str, *, offset: int, limit: int,
) -> dict[str, Any] | None:
    value = get_factor_set(username, target_ref)
    if value is None:
        return None
    return factor_set_page(value, offset=offset, limit=limit)


def factor_set_page(value: dict[str, Any], *, offset: int, limit: int) -> dict[str, Any]:
    """Page the same validated frozen members for authored and mirrored sets."""
    frozen = require_frozen_factor_set(value)
    members = frozen["identity"]["members"]
    offset = max(0, int(offset))
    limit = max(1, min(1000, int(limit)))
    page = members[offset:offset + limit]
    return {
        **_summary(value),
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(page) < len(members),
        "next_offset": offset + len(page),
        "related_references": [
            {
                "relation": "集合成员",
                "kind": "factor",
                "target_ref": member["ref"],
                "label": member["alias"],
                "data": member,
            }
            for member in page
        ],
    }


def factor_set_descriptor(
    username: str, target_ref: str,
) -> dict[str, Any] | None:
    """Return the exact immutable descriptor required by Run submission."""
    value = get_factor_set(username, target_ref)
    if value is None:
        return None
    return {
        "target_ref": value["ref"],
        "manifest": _manifest(value),
    }


def unregister_factor_set(username: str, target_ref: str) -> bool:
    return delete_factor_set(username, target_ref)


def _summary(value: dict[str, Any]) -> dict[str, Any]:
    identity = require_frozen_factor_set(value)["identity"]
    return {
        "schema_version": value["schema_version"],
        "target_ref": value["ref"],
        "owner_ref": value["owner_ref"],
        "set_id": identity["set_id"],
        "title_zh": value["alias"],
        "description_zh": str(value.get("description") or ""),
        "member_fingerprint": identity["member_fingerprint"],
        "member_count": len(identity["members"]),
        "authority": value.get("authority"),
        "owner_username": value.get("owner_username"),
        "can_edit": (
            str(value.get("owner_ref") or "")
            == f"principal:{value.get('owner_username')}"
        ),
        "updated_at": value.get("updated_at"),
    }


def _manifest(value: dict[str, Any]) -> dict[str, Any]:
    result = {
        key: value[key]
        for key in ("schema_version", "ref", "alias", "owner_ref", "identity")
    }
    if value.get("description"):
        result["description"] = str(value["description"])
    return result
