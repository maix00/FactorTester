"""Compact, deterministic protocol contract for remote clients."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any


PROTOCOL_NAME = "factortester-remote-research"
PROTOCOL_CURRENT = 1
MINIMUM_CLIENT_PROTOCOL = 1

_CAPABILITIES = (
    ("auth.session", 1),
    ("factor.workspace", 1),
    ("research.run", 1),
    ("research.job", 1),
    ("products.liquidity", 1),
)


def protocol_manifest() -> dict[str, Any]:
    """Return capability IDs only; full contracts remain server-side."""
    payload: dict[str, Any] = {
        "schema_version": 1,
        "protocol": {
            "name": PROTOCOL_NAME,
            "current": PROTOCOL_CURRENT,
            "minimum_client": MINIMUM_CLIENT_PROTOCOL,
        },
        "capabilities": [
            {"id": capability_id, "version": version}
            for capability_id, version in _CAPABILITIES
        ],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {**payload, "manifest_hash": sha256(canonical).hexdigest()}
