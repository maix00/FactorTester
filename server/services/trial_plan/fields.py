"""Primitive validators shared by the TrialPlan contract."""

from __future__ import annotations

import math
import re
from typing import Any


SHA256 = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")
LOCAL_DRIVE_PATH = re.compile(r"^[A-Za-z]:[\\/]")
FORBIDDEN_PRIVATE_KEYS = frozenset({
    "chain_of_thought",
    "factor_source",
    "formula",
    "local_path",
    "private_path",
    "reasoning",
    "source",
    "source_code",
})


def object_field(
    value: Any,
    path: str,
    *,
    fields: frozenset[str],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    missing = sorted(fields - set(value))
    extra = sorted(set(value) - fields)
    if missing:
        raise ValueError(f"{path} missing fields: {', '.join(missing)}")
    if extra:
        raise ValueError(f"{path} has unsupported fields: {', '.join(extra)}")
    return value


def array_field(value: Any, path: str, *, allow_empty: bool) -> list[Any]:
    if not isinstance(value, list) or (not allow_empty and not value):
        qualifier = "non-empty " if not allow_empty else ""
        raise ValueError(f"{path} must be a {qualifier}array")
    return value


def identifier_field(value: Any, path: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError(f"{path} must be a compact opaque identifier")
    return value


def identifier_list(
    value: Any,
    path: str,
    *,
    allow_empty: bool = True,
) -> list[str]:
    items = array_field(value, path, allow_empty=allow_empty)
    normalized = [
        identifier_field(item, f"{path}[{index}]")
        for index, item in enumerate(items)
    ]
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{path} must not contain duplicates")
    return normalized


def sha256_field(value: Any, path: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{path} must be a sha256 string")
    normalized = value.removeprefix("sha256:")
    if not SHA256.fullmatch(normalized):
        raise ValueError(f"{path} must be a sha256 string")
    return normalized


def sha256_list(value: Any, path: str) -> list[str]:
    items = array_field(value, path, allow_empty=False)
    hashes = [
        sha256_field(item, f"{path}[{index}]")
        for index, item in enumerate(items)
    ]
    if len(hashes) != len(set(hashes)):
        raise ValueError(f"{path} must not contain duplicates")
    return hashes


def integer_field(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{path} must be an integer")
    return value


def positive_integer(value: Any, path: str) -> int:
    result = integer_field(value, path)
    if result < 1:
        raise ValueError(f"{path} must be positive")
    return result


def json_value(value: Any, path: str) -> Any:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must be finite")
        return value
    if isinstance(value, str):
        if (
            value.startswith(("/", "~/", "\\"))
            or LOCAL_DRIVE_PATH.match(value)
        ):
            raise ValueError(f"{path} may not contain a private local path")
        return value
    if isinstance(value, list):
        return [
            json_value(item, f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if isinstance(value, dict):
        forbidden = sorted(set(value).intersection(FORBIDDEN_PRIVATE_KEYS))
        if forbidden:
            raise ValueError(
                f"{path} may not contain private/source fields: "
                + ", ".join(forbidden)
            )
        return {
            identifier_field(key, f"{path}.key"): json_value(
                item,
                f"{path}.{key}",
            )
            for key, item in value.items()
        }
    raise ValueError(f"{path} contains a non-JSON value")
