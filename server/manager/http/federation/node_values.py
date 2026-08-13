"""Validation and wire conversion for node-control HTTP values."""

from __future__ import annotations

from urllib.parse import parse_qs

from server.manager.transfers.node_protocol import command_payload


def query_value(parsed, name: str, *, required: bool = True) -> str:
    value = str(parse_qs(parsed.query).get(name, [""])[0] or "").strip()
    if required and not value:
        raise ValueError(f"{name} is required")
    return value


def reachability(value: object) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        items = value.split(",")
    elif isinstance(value, (list, tuple, set, frozenset)):
        items = value
    else:
        raise ValueError("reachable_from must be a list")
    return tuple(sorted({
        str(item).strip() for item in items if str(item).strip()
    }))


def command_response(values) -> dict[str, object]:
    return {
        "success": True,
        "commands": [command_payload(value) for value in values],
    }
