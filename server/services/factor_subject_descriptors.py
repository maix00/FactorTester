"""Validate formula-addressed factor sets attached to a RunSpec."""

from __future__ import annotations

from typing import Any

from tools.cli.factor_subject_refs import factor_subject_kind
from tools.factors.factor_set_identity import require_frozen_factor_set


def validate_factor_subject_descriptors(value: Any) -> list[dict[str, Any]]:
    if value in (None, []):
        return []
    if not isinstance(value, list) or len(value) > 32:
        raise ValueError("factor_subject_descriptors must contain at most 32 items")
    result = [_validate_factor_set(item) for item in value]
    refs = [item["target_ref"] for item in result]
    if len(set(refs)) != len(refs):
        raise ValueError("factor subject descriptors must be unique")
    return result


def assert_factor_sets_match_run(
    descriptors: list[dict[str, Any]], *, factor_refs: set[str],
) -> None:
    if not descriptors:
        return
    declared = {
        member["ref"]
        for descriptor in descriptors
        for member in descriptor["members"]
    }
    if declared != factor_refs:
        missing = sorted(factor_refs - declared)
        extra = sorted(declared - factor_refs)
        raise ValueError(
            "factor-set members must exactly match the RunSpec frozen factors; "
            f"missing_refs={missing}, extra_refs={extra}"
        )


def compact_factor_subject_descriptors(
    descriptors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    allowed = (
        "target_ref", "member_fingerprint", "member_count", "authority",
    )
    return [
        {key: descriptor[key] for key in allowed}
        for descriptor in descriptors
    ]


def factor_refs_by_alias(
    descriptors: list[dict[str, Any]],
) -> dict[str, str]:
    bindings: dict[str, str] = {}
    for descriptor in descriptors:
        for member in descriptor.get("members") or []:
            alias = member["alias"]
            target_ref = member["ref"]
            previous = bindings.get(alias)
            if previous is not None and previous != target_ref:
                raise ValueError(
                    "one factor alias is bound to multiple formula identities"
                )
            bindings[alias] = target_ref
    return bindings


def _validate_factor_set(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"target_ref", "manifest"}:
        raise ValueError("factor subject descriptor fields are invalid")
    target_ref = str(value.get("target_ref") or "")
    if factor_subject_kind(target_ref) != "factor_set":
        raise ValueError("factor subject descriptor must identify factor-set:v2")
    manifest = value.get("manifest")
    try:
        frozen = require_frozen_factor_set(manifest)
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"factor-set descriptor manifest is invalid: {error}"
        ) from error
    members = frozen["identity"]["members"]
    if len(members) > 1024:
        raise ValueError("factor-set descriptor members are invalid")
    if frozen["ref"] != target_ref:
        raise ValueError("factor-set descriptor ref does not match its manifest")
    member_refs = [member["ref"] for member in members]
    return {
        "target_ref": target_ref,
        "member_fingerprint": frozen["identity"]["member_fingerprint"],
        "member_count": len(members),
        "members": members,
        "member_refs": member_refs,
        "member_aliases": [item["alias"] for item in members],
        "authority": "formula_manifest",
    }


__all__ = [
    "assert_factor_sets_match_run",
    "compact_factor_subject_descriptors",
    "factor_refs_by_alias",
    "validate_factor_subject_descriptors",
]
