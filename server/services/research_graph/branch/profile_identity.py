"""Validation helpers for opaque, user-scoped Agent Profile references."""

from __future__ import annotations

import re
from typing import Any


_PROFILE_REF = re.compile(r"^profile:[A-Za-z0-9._$@-]{1,120}$")
_AUTHORIZATION_REF = re.compile(
    r"^[A-Za-z][A-Za-z0-9+.-]*:[A-Za-z0-9._$@-]{1,240}$"
)


def validate_profile_ref(value: Any, *, field: str = "profile_ref") -> str:
    """Return one stable profile ref; never accept a path or display name."""
    if not isinstance(value, str) or not _PROFILE_REF.fullmatch(value):
        raise ValueError(f"{field} must use profile:<stable-id>")
    return value


def optional_profile_ref(value: Any, *, field: str = "profile_ref") -> str:
    if value in (None, ""):
        return ""
    return validate_profile_ref(value, field=field)


def validate_authorization_ref(value: Any) -> str:
    """Validate a bounded opaque approval reference without storing its body."""
    if not isinstance(value, str) or not _AUTHORIZATION_REF.fullmatch(value):
        raise ValueError(
            "authorization_ref must use a stable scheme-qualified reference"
        )
    return value
