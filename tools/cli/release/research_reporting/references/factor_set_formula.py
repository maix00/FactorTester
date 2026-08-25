"""Compatibility import surface for the central FactorSet identity adapter."""

from __future__ import annotations

from collections.abc import Iterable

from tools.factors.factor_set_identity import (
    build_factor_set_reference,
    factor_set_identity_payload,
    require_factor_set_reference,
    verify_factor_set_reference,
)
from tools.factors.formula_identity import require_factor_reference


def canonical_factor_set_members(member_refs: Iterable[str]) -> list[str]:
    members = sorted(require_factor_reference(value) for value in member_refs)
    if not members:
        raise ValueError("factor set members must be non-empty")
    if len(members) != len(set(members)):
        raise ValueError("factor set members must be unique")
    return members


def parse_factor_set_reference(value: str) -> dict[str, str]:
    ref = require_factor_set_reference(value)
    return {"identity_digest": ref.rsplit(":", 1)[-1]}


__all__ = [
    "build_factor_set_reference",
    "canonical_factor_set_members",
    "factor_set_identity_payload",
    "parse_factor_set_reference",
    "verify_factor_set_reference",
]
