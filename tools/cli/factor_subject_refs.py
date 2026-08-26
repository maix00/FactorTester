"""Typed identities for the factor subject of research evidence and claims."""

from __future__ import annotations

from tools.cli.identities.factor_set import is_factor_set_reference
from tools.cli.identities.factor import (
    is_factor_family_reference,
    is_factor_reference,
)

_OWNER_NAMESPACES = frozenset({
    "device",
    "org",
    "principal",
    "profile",
    "team",
    "user",
})
_TYPED_FACTOR_PREFIXES = ("factor:", "factor-family:", "factor-set:")


def split_owner_qualified_factor_family(value: str) -> tuple[str | None, str]:
    """Split a catalog family selector without truncating a namespaced owner.

    Namespaced owners are stable references such as ``profile:maxa``.  A
    selector therefore appends the family as a third segment, for example
    ``profile:maxa:MmRateOfChg``.  The owner reference alone is deliberately
    rejected because it does not identify a factor family.
    """
    text = str(value or "").strip()
    if not text:
        raise ValueError("factor family reference must be non-empty text")
    if text.startswith(_TYPED_FACTOR_PREFIXES):
        raise ValueError(
            "typed factor references cannot be used as factor family selectors"
        )
    if ":" not in text:
        return None, text

    parts = text.split(":")
    namespace = parts[0]
    if namespace in _OWNER_NAMESPACES:
        if len(parts) < 3 or not parts[-1]:
            raise ValueError(
                "owner reference is not a factor family reference; append the family"
            )
        owner = ":".join(parts[:-1])
        family = parts[-1]
        return owner, family

    if namespace in {"public", "$COMMON"}:
        if len(parts) != 2 or not parts[1]:
            raise ValueError("public factor family reference is invalid")
        return "public", parts[1]

    owner, family = text.split(":", 1)
    if not owner or not family:
        raise ValueError("owner-qualified factor family reference is invalid")
    return owner, family


def factor_reference_kind(value: str) -> str:
    """Return the exact factor reference class, including navigation-only families."""
    if is_factor_reference(value):
        return "factor"
    if is_factor_family_reference(value):
        return "factor_family"
    if is_factor_set_reference(value):
        return "factor_set"
    raise ValueError(
        "factor reference must be factor:v2, factor-family:v2, or factor-set:v2"
    )


def factor_subject_kind(value: str) -> str:
    """Return an executable research subject class.

    A factor family is a source/catalog navigation object.  It is deliberately
    excluded from checkpoints, Evidence applicability, and transitions.
    """
    kind = factor_reference_kind(value)
    if kind == "factor_family":
        raise ValueError(
            "factor family references are navigation-only and cannot be "
            "research subjects"
        )
    return kind


def validate_factor_subject_ref(
    value: object,
) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("factor subject ref must be non-empty text")
    factor_subject_kind(value)
    return value
