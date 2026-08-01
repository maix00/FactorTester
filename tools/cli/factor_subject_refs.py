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
_LEGACY_CATALOG_FACTOR = re.compile(r"^factor:[^:\s]+:[^:\s]+$")


def factor_subject_kind(value: str, *, allow_legacy: bool = False) -> str:
    """Return the exact identity class, rejecting lookup-only set references."""
    if _FROZEN_FACTOR.fullmatch(value):
        return "factor_family" if value.startswith("factor-family:") else "factor"
    if _FROZEN_FACTOR_SET.fullmatch(value):
        return "factor_set"
    if _JOB_FACTOR_EXPR.fullmatch(value):
        return "factor_expr_execution"
    if allow_legacy and _LEGACY_CATALOG_FACTOR.fullmatch(value):
        return "legacy_catalog_factor"
    raise ValueError(
        "factor subject ref must be a frozen factor:v1, factor-family:v1, "
        "factor-set:v1, or factor-expr execution identity"
    )


def validate_factor_subject_ref(
    value: object,
    *,
    allow_legacy: bool = False,
) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("factor subject ref must be non-empty text")
    factor_subject_kind(value, allow_legacy=allow_legacy)
    return value


def frozen_factor_identity(value: str) -> str:
    """Return the exact FactorExpr identity carried by a frozen factor ref."""
    kind = factor_subject_kind(value)
    if kind not in {"factor", "factor_family"}:
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
