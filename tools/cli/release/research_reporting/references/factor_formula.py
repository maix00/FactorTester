"""Compatibility import surface for the central Factor identity adapter."""

from __future__ import annotations

from tools.cli.identities.factor import (
    build_factor_family_reference,
    build_factor_reference,
    factor_family_identity_payload,
    factor_identity_payload,
    require_factor_family_reference,
    require_factor_reference,
    verify_factor_family_reference,
    verify_factor_reference,
)


def parse_factor_reference(value: str) -> dict[str, str]:
    ref = require_factor_reference(value)
    return {"identity_digest": ref.rsplit(":", 1)[-1]}


def parse_factor_family_reference(value: str) -> dict[str, str]:
    ref = require_factor_family_reference(value)
    return {"identity_digest": ref.rsplit(":", 1)[-1]}


def validate_factor_reference(
    *, kind: str, target_ref: str, roots: object = None,
) -> dict[str, str]:
    del roots
    if kind != "factor":
        raise ValueError("factor reference kind is invalid")
    if str(target_ref).startswith("factor:v2:"):
        parse_factor_reference(target_ref)
        object_kind = "factor"
    elif str(target_ref).startswith("factor-family:v2:"):
        parse_factor_family_reference(target_ref)
        object_kind = "factor-family"
    else:
        raise ValueError("factor reference must use the v2 formula format")
    return {"kind": "factor", "object_kind": object_kind, "target_ref": target_ref}


__all__ = [
    "build_factor_family_reference",
    "build_factor_reference",
    "factor_family_identity_payload",
    "factor_identity_payload",
    "parse_factor_family_reference",
    "parse_factor_reference",
    "validate_factor_reference",
    "verify_factor_family_reference",
    "verify_factor_reference",
]
