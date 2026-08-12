"""Content-addressed operational Budget Profiles outside Graph content."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import time
from typing import Any

import orjson
import settings as Settings


DEFAULT_RUNTIME_AGENT_PACKET_BYTES = 6400
MAX_AGENT_PACKET_HARD_CEILING_BYTES = 16 * 1024
_PROFILE_STORE_NAME = "research-runtime-budget-profiles.json"
_PROFILE_CACHE: dict[str, dict[str, Any]] = {}


def configure_runtime_packet_budget_profile(
    *,
    ceiling_bytes: int,
    actor: str,
    provider_id: str = "",
    model_id: str = "",
    tokenizer_id: str = "",
    tokenizer_revision: str = "",
    calibration_receipt_ref: str = "",
    calibration_receipt_hash: str = "",
) -> dict[str, Any]:
    """Create and activate one operational profile without changing a Graph."""
    ceiling = int(ceiling_bytes)
    if ceiling <= 0 or ceiling > MAX_AGENT_PACKET_HARD_CEILING_BYTES:
        raise ValueError(
            "runtime packet budget exceeds the protocol safety boundary"
        )
    if bool(calibration_receipt_ref) != bool(calibration_receipt_hash):
        raise ValueError(
            "packet calibration receipt ref and hash must be paired"
        )
    value = {
        "schema_version": 1,
        "ceiling_bytes": ceiling,
        "protocol_hard_ceiling_bytes": (
            MAX_AGENT_PACKET_HARD_CEILING_BYTES
        ),
        "provider_id": str(provider_id),
        "model_id": str(model_id),
        "tokenizer_id": str(tokenizer_id),
        "tokenizer_revision": str(tokenizer_revision),
        "calibration_receipt_ref": str(calibration_receipt_ref),
        "calibration_receipt_hash": str(calibration_receipt_hash),
        "calibration_status": (
            "receipt_declared_unverified"
            if calibration_receipt_ref else "uncalibrated"
        ),
    }
    profile_hash = _content_hash(value)
    value.update({
        "base_profile_hash": profile_hash,
        "profile_ref": f"agent-packet-runtime:{profile_hash}",
        "created_by": str(actor),
        "created_at": time.time(),
    })
    path = _profile_store_path()
    store = _load_profile_store(path)
    profiles = dict(store.get("profiles") or {})
    profiles.setdefault(profile_hash, value)
    updated = {
        "schema_version": 1,
        "active_profile_hash": profile_hash,
        "profiles": profiles,
    }
    _write_profile_store(path, updated)
    _PROFILE_CACHE[str(path)] = updated
    return dict(profiles[profile_hash])


def active_runtime_packet_budget_configuration() -> dict[str, Any]:
    """Return the active operational profile without Graph-derived coverage."""
    path = _profile_store_path()
    store = _load_profile_store(path)
    active_hash = str(store.get("active_profile_hash") or "")
    profiles = store.get("profiles") or {}
    if active_hash and isinstance(profiles.get(active_hash), dict):
        return dict(profiles[active_hash])
    return _default_runtime_profile()


def reset_runtime_packet_budget_cache() -> None:
    """Test/process-reload hook; ordinary requests use the in-process cache."""
    _PROFILE_CACHE.clear()


def _default_runtime_profile() -> dict[str, Any]:
    raw_ceiling = os.environ.get(
        "GTHT_AGENT_PACKET_CEILING_BYTES",
        str(DEFAULT_RUNTIME_AGENT_PACKET_BYTES),
    )
    try:
        ceiling = int(raw_ceiling)
    except ValueError as exc:
        raise ValueError(
            "GTHT_AGENT_PACKET_CEILING_BYTES must be an integer"
        ) from exc
    value = {
        "schema_version": 1,
        "ceiling_bytes": ceiling,
        "protocol_hard_ceiling_bytes": (
            MAX_AGENT_PACKET_HARD_CEILING_BYTES
        ),
        "provider_id": "",
        "model_id": "",
        "tokenizer_id": "",
        "tokenizer_revision": "",
        "calibration_receipt_ref": "",
        "calibration_receipt_hash": "",
        "calibration_status": "uncalibrated",
    }
    profile_hash = _content_hash(value)
    return {
        **value,
        "base_profile_hash": profile_hash,
        "profile_ref": f"agent-packet-runtime:{profile_hash}",
        "created_by": "server-default",
        "created_at": 0.0,
    }


def _profile_store_path() -> Path:
    return Path(Settings.CACHE_DIR) / _PROFILE_STORE_NAME


def _load_profile_store(path: Path) -> dict[str, Any]:
    cache_key = str(path)
    cached = _PROFILE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    if not path.exists():
        store = {
            "schema_version": 1,
            "active_profile_hash": "",
            "profiles": {},
        }
    else:
        store = orjson.loads(path.read_bytes())
        if (
            not isinstance(store, dict)
            or int(store.get("schema_version") or 0) != 1
            or not isinstance(store.get("profiles"), dict)
        ):
            raise ValueError("runtime Budget Profile store is invalid")
    _PROFILE_CACHE[cache_key] = store
    return store


def _write_profile_store(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(
        orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
    )
    os.replace(temporary, path)


def _content_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()
