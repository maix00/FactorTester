"""Canonical authoring identity contract for factor settings."""

from __future__ import annotations


FACTOR_ID_KEYS = ("ref",)
FACTOR_LABEL_KEYS = ("alias",)
FACTOR_ITEM_FIELDS = (
    "schema_version", "ref", "alias", "owner_ref", "identity",
    "source_kind", "transient_factor_id",
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
