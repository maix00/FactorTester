"""Canonical authoring identity contract for factor settings."""

from __future__ import annotations


FACTOR_ID_KEYS = ("factor_ref", "target_ref")
FACTOR_LABEL_KEYS = ("factor_alias", "alias", "name", "label")
FACTOR_ITEM_FIELDS = (
    "factor_ref", "factor_alias", "factor_owner_ref", "factor_git_commit",
    "factor_family_ref", "factor_params", "owner_ref", "git_commit",
    "git_blob", "relative_path", "factor_family_alias", "family_ref",
    "params", "source_kind", "transient_factor_id",
)


def factor_identity_serialization() -> dict[str, tuple[str, ...]]:
    return {
        "id_keys": FACTOR_ID_KEYS,
        "label_keys": FACTOR_LABEL_KEYS,
        "item_fields": FACTOR_ITEM_FIELDS,
    }


__all__ = [
    "FACTOR_ID_KEYS", "FACTOR_ITEM_FIELDS", "FACTOR_LABEL_KEYS",
    "factor_identity_serialization",
]
