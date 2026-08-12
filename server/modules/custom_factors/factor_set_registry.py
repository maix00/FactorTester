"""Server registry for explicitly synchronized immutable factor sets."""

from __future__ import annotations

from typing import Any

from server.services.factor_subject_descriptors import (
    validate_factor_subject_descriptors,
)
from tools.cli.factor_subject_refs import frozen_factor_identity
from tools.data.account_manage import (
    delete_factor_set,
    get_factor_set,
    list_factor_sets,
    save_factor_set,
)


def register_factor_set(
    username: str, descriptor: dict[str, Any],
) -> dict[str, Any]:
    validated = validate_factor_subject_descriptors([descriptor])[0]
    manifest = descriptor["manifest"]
    value = {
        "schema_version": 1,
        "target_ref": validated["target_ref"],
        "set_ref": validated["set_ref"],
        "set_id": manifest["set_id"],
        "title_zh": manifest["title_zh"],
        "description_zh": str(manifest.get("description_zh") or ""),
        "member_refs": list(manifest["member_refs"]),
        "member_hash": validated["member_hash"],
        "member_count": validated["member_count"],
        "authority": validated["authority"],
        "owner_username": username,
    }
    return save_factor_set(username, value)


def factor_set_catalog(username: str, query: str = "") -> list[dict[str, Any]]:
    needle = query.strip().casefold()
    values = list_factor_sets(username)
    if needle:
        values = [
            value for value in values
            if needle in " ".join([
                str(value.get("set_id") or ""),
                str(value.get("title_zh") or ""),
                str(value.get("description_zh") or ""),
                str(value.get("set_ref") or ""),
            ]).casefold()
        ]
    return [_summary(value) for value in values]


def factor_set_detail(
    username: str, target_ref: str, *, offset: int, limit: int,
) -> dict[str, Any] | None:
    value = get_factor_set(username, target_ref)
    if value is None:
        return None
    members = list(value.get("member_refs") or [])
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
                "target_ref": target_ref,
                "label": frozen_factor_identity(target_ref),
            }
            for target_ref in page
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
        "target_ref": value["target_ref"],
        "manifest": {
            "schema_version": 1,
            "set_id": value["set_id"],
            "set_ref": value["set_ref"],
            "title_zh": value["title_zh"],
            "description_zh": str(value.get("description_zh") or ""),
            "member_refs": list(value.get("member_refs") or []),
            "member_hash": value["member_hash"],
        },
    }


def unregister_factor_set(username: str, target_ref: str) -> bool:
    return delete_factor_set(username, target_ref)


def _summary(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.get(key) for key in (
            "schema_version", "target_ref", "set_ref", "set_id", "title_zh",
            "description_zh", "member_hash", "member_count", "authority",
            "owner_username", "updated_at",
        )
    }
