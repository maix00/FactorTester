"""Validate stable refs and derive source-free research scope identity."""

from __future__ import annotations

import hashlib
import json
import math
import ntpath
import posixpath
import re
from typing import Any
from urllib.parse import urlsplit


PROHIBITED_KEYS = {
    "api_key", "credential", "credentials", "expression_tree",
    "factor_source", "formula", "password", "raw_stderr", "raw_stdout",
    "secret", "source_code", "token",
}
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_REF = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\\\s]{1,511}$")
_SCOPE_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
_LOCAL_PATH = re.compile(
    r'''(?:^|[\s"'`(\[=:])(?:~[/\\]|[A-Za-z]:[/\\]|/(?!/))'''
)
_CHINESE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def reference(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _REF.fullmatch(value):
        raise ValueError(f"{field} must be a stable reference")
    parsed = urlsplit(value)
    network_reference = parsed.scheme.lower() in {"http", "https"}
    logical_absolute_path = (
        not parsed.netloc
        and (
            parsed.path.startswith(("/", "~"))
            or ntpath.isabs(parsed.path)
            or bool(ntpath.splitdrive(parsed.path)[0])
        )
    )
    if (
        parsed.scheme.lower() == "file"
        or (bool(parsed.netloc) and not network_reference)
        or (network_reference and not parsed.netloc)
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.query)
        or bool(parsed.fragment)
        or logical_absolute_path
        or posixpath.isabs(value)
        or ntpath.isabs(value)
        or "\\" in value
        or re.search(r"(?:^|/)\.\.?($|/)", parsed.path)
    ):
        raise ValueError(f"{field} must be a stable reference")
    return value


def ref_id(value: str, scheme: str) -> str:
    prefix = scheme + ":"
    if not value.startswith(prefix):
        raise ValueError(f"reference must use {scheme}: scheme")
    return safe_id(value[len(prefix):], scheme)


def safe_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise ValueError(f"{field} must be a safe identifier")
    return value


def bounded_text(value: Any, field: str, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.encode()) > maximum:
        raise ValueError(f"{field} must be bounded text")
    return value


def chinese_text(value: Any, field: str, maximum: int = 512) -> str:
    text = bounded_text(value, field, maximum=maximum)
    if not contains_chinese(text):
        raise ValueError(f"{field} must contain Simplified Chinese prose")
    return text


def contains_chinese(value: str) -> bool:
    return _CHINESE.search(value) is not None


def scope_identity(scope: Any) -> dict[str, Any]:
    """Return a non-reversible audit identity for one bounded local scope."""
    canonical = _canonical_scope_value(scope, depth=0)
    if not isinstance(canonical, dict) or not canonical:
        raise ValueError("research scope must be a non-empty object")
    payload = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(payload) > 8 * 1024:
        raise ValueError("research scope exceeds 8192 bytes")
    digest = hashlib.sha256(payload).hexdigest()
    return {
        "fields": sorted(canonical),
        "scope_hash": digest,
        "scope_ref": f"scope:sha256:{digest}",
    }


def reject_prohibited(value: Any, *, label: str = "checkpoint") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).lower() in PROHIBITED_KEYS:
                raise ValueError(f"prohibited {label} field: {key}")
            reject_prohibited(nested, label=label)
    elif isinstance(value, list):
        for item in value:
            reject_prohibited(item, label=label)


def _canonical_scope_value(value: Any, *, depth: int) -> Any:
    if depth > 4:
        raise ValueError("research scope nesting is too deep")
    if isinstance(value, dict):
        if len(value) > 32:
            raise ValueError("research scope object is too large")
        result = {}
        for key in sorted(value):
            if not isinstance(key, str) or not _SCOPE_KEY.fullmatch(key):
                raise ValueError("research scope key is invalid")
            if key.lower() in PROHIBITED_KEYS:
                raise ValueError(f"prohibited research scope field: {key}")
            result[key] = _canonical_scope_value(value[key], depth=depth + 1)
        return result
    if isinstance(value, list):
        if len(value) > 32:
            raise ValueError("research scope array is too large")
        return [
            _canonical_scope_value(item, depth=depth + 1) for item in value
        ]
    if value is None or type(value) in {bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("research scope number must be finite")
        return value
    if isinstance(value, str):
        if len(value.encode("utf-8")) > 256 or _LOCAL_PATH.search(value):
            raise ValueError("research scope text is unsafe or too large")
        return value
    raise ValueError("research scope value type is unsupported")
