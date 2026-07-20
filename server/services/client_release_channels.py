"""Read signed update manifests from disk without database access."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from tools.cli.release.update_channel import (
    MAX_UPDATE_MANIFEST_BYTES,
    validate_update_manifest,
)


def load_client_release_channel(
    root: Path,
    channel: str,
    *,
    public_key: Path,
) -> tuple[bytes, str]:
    if channel not in {"stable", "beta"}:
        raise ValueError("client release channel is invalid")
    path = root.resolve() / f"{channel}.json"
    raw = path.read_bytes()
    if len(raw) > MAX_UPDATE_MANIFEST_BYTES:
        raise ValueError("update manifest exceeds size limit")
    value: Any = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("update manifest must be a JSON object")
    validate_update_manifest(
        value,
        public_key=public_key,
        expected_channel=channel,
    )
    return raw, sha256(raw).hexdigest()
