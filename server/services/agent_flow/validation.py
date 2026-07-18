"""Shared Agent Flow value validation and deterministic hashing."""

from __future__ import annotations

import hashlib
from typing import Any

import orjson


CHARGING_POLICY_VERSION = "normalized-total@1"
RESERVED = "reserved"
SETTLED = "settled"


def require_text(field: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")


def require_sha256(field: str, value: str) -> None:
    if (
        len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field} must be sha256")


def require_non_negative(field: str, value: int) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
    ):
        raise ValueError(f"{field} must be a non-negative integer")


def optional_hash(value: str) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode()).hexdigest()


def invocation_request_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()
