"""Stable public references, cursors, and projection bounds."""

from __future__ import annotations

import base64
import hashlib
import math
from typing import Any

import orjson

from server.services.research_graph.report_checkpoint import (
    safe_identifier as _safe_identifier,
)

MAX_PROJECTION_BYTES = 64 * 1024

def bounded_limit(value: Any, *, default: int, maximum: int) -> int:
    if value in (None, ""):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be an integer") from exc
    if parsed < 1 or parsed > maximum:
        raise ValueError(f"limit must be between 1 and {maximum}")
    return parsed


def workspace_ref_for(workspace_id: str) -> str:
    return f"workspace:{_identifier(workspace_id, field='workspace_id')}"


def parse_workspace_ref(value: str) -> str:
    if not isinstance(value, str) or not value.startswith("workspace:"):
        raise ValueError("workspace_ref must use workspace:<id>")
    return _identifier(
        value.removeprefix("workspace:"),
        field="workspace_ref",
    )


def work_package_ref_for(instance_id: str) -> str:
    return f"work-package:{_identifier(instance_id, field='instance_id')}"


def parse_work_package_ref(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("research_ref must be a string")
    parts = value.split(":")
    if len(parts) != 2 or parts[0] != "work-package":
        raise ValueError("research_ref must use work-package:<instance>")
    return _identifier(parts[1], field="instance_id")


def research_ref_for(instance_id: str, branch_id: str) -> str:
    return (
        "graph-branch:"
        f"{_identifier(instance_id, field='instance_id')}:"
        f"{_identifier(branch_id, field='branch_id')}"
    )


def parse_research_ref(value: str) -> tuple[str, str]:
    if not isinstance(value, str):
        raise ValueError("research_ref must be a string")
    parts = value.split(":")
    if len(parts) != 3 or parts[0] != "graph-branch":
        raise ValueError(
            "research_ref must use graph-branch:<instance>:<branch>"
        )
    return (
        _identifier(parts[1], field="instance_id"),
        _identifier(parts[2], field="branch_id"),
    )


def encode_cursor(*, kind: str, at: float, identifier: str) -> str:
    payload = orjson.dumps({
        "v": 1,
        "kind": kind,
        "at": float(at),
        "id": _identifier(identifier, field="cursor id"),
    })
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_cursor(value: str, *, kind: str) -> dict[str, Any]:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ValueError("invalid cursor")
    try:
        padding = "=" * (-len(value) % 4)
        decoded = orjson.loads(
            base64.urlsafe_b64decode((value + padding).encode())
        )
        if (
            not isinstance(decoded, dict)
            or decoded.get("v") != 1
            or decoded.get("kind") != kind
        ):
            raise ValueError
        at = float(decoded["at"])
        if not math.isfinite(at):
            raise ValueError
        identifier = _identifier(decoded["id"], field="cursor id")
    except (KeyError, TypeError, ValueError, orjson.JSONDecodeError) as exc:
        raise ValueError("invalid cursor") from exc
    return {"at": at, "id": identifier}


def projection_etag(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()


def bounded_projection(value: dict[str, Any]) -> dict[str, Any]:
    size = len(orjson.dumps(value))
    if size > MAX_PROJECTION_BYTES:
        raise ValueError(
            f"profile research projection exceeds {MAX_PROJECTION_BYTES} bytes"
        )
    return value



def _identifier(value: Any, *, field: str) -> str:
    normalized = _safe_identifier(value)
    if not normalized:
        raise ValueError(f"{field} is invalid")
    return normalized
