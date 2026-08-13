"""Validation and wire conversion for node-control HTTP values."""

from __future__ import annotations

from urllib.parse import parse_qs

def query_value(parsed, name: str, *, required: bool = True) -> str:
    value = str(parse_qs(parsed.query).get(name, [""])[0] or "").strip()
    if required and not value:
        raise ValueError(f"{name} is required")
    return value
