"""Typed identities for the factor subject of research evidence and claims."""

from __future__ import annotations

from base64 import urlsafe_b64decode
import re


_FROZEN_FACTOR = re.compile(
    r"^(?:factor|factor-family):v1:[A-Za-z0-9._-]+:"
    r"[A-Za-z0-9_-]+:[A-Za-z0-9_-]+:[0-9a-f]{40,64}:[0-9a-f]{40,64}$"
)
_FROZEN_FACTOR_SET = re.compile(
    r"^factor-set:v1:[A-Za-z0-9._-]+:[A-Za-z0-9_-]+:"
    r"[A-Za-z0-9_-]+:[0-9a-f]{40,64}:[0-9a-f]{40,64}$"
)
_JOB_FACTOR_EXPR = re.compile(r"^factor-expr:.+@sha256:[0-9a-f]{64}$")
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
    if _FROZEN_FACTOR.fullmatch(value):
        return "factor_family" if value.startswith("factor-family:") else "factor"
    if _FROZEN_FACTOR_SET.fullmatch(value):
        return "factor_set"
    if _JOB_FACTOR_EXPR.fullmatch(value):
        return "factor_expr_execution"
    raise ValueError(
        "factor reference must be factor:v1, factor-family:v1, factor-set:v1, "
        "or a factor-expr execution identity"
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


def frozen_factor_identity(value: str) -> str:
    """Return the exact FactorExpr identity carried by a frozen factor ref."""
    kind = factor_subject_kind(value)
    if kind != "factor":
        raise ValueError("factor subject does not carry one FactorExpr identity")
    encoded = value.split(":", 7)[4]
    try:
        padding = "=" * (-len(encoded) % 4)
        identity = urlsafe_b64decode(encoded + padding).decode("utf-8")
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError("factor subject identity is invalid") from error
    if not identity:
        raise ValueError("factor subject identity is empty")
    return identity


def frozen_factor_family(value: str) -> str:
    """Return the family name carried by a frozen FactorExpr identity."""
    family = frozen_factor_identity(value).split("|", 1)[0].strip()
    if not family:
        raise ValueError("factor subject family is empty")
    return family
