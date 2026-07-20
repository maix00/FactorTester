"""Bounded current-state projections owned by one Hypothesis Branch."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any

import orjson


_RESOLUTION_LIST_FIELDS = (
    "bindings",
    "gaps",
    "triggered_conditional_bindings",
    "triggered_conditional_gaps",
    "undetermined_conditions",
)
_RESOLUTION_ITEM_FIELDS = (
    "capability_id",
    "capability_description",
    "descriptor_hash",
    "reason",
    "required_by",
    "explanation",
)
_SERVER_FORBIDDEN_IDENTITY_FIELDS = {
    "skill_name",
    "implementation_id",
    "provider",
    "source_path",
    "source_fingerprint",
    "loaded_skill_ids",
    "loaded_skill_receipts",
}
_MAX_RESOLUTION_BYTES = 4096


def normalize_capability_resolution(
    resolution: dict[str, Any],
    *,
    node_id: str,
) -> dict[str, Any]:
    """Remove runtime/Skill identity and retain only node-local semantics."""
    if not isinstance(resolution, dict):
        raise ValueError("capability_resolution must be an object")
    _reject_server_identity(resolution, location="capability_resolution")
    declared_node = str(resolution.get("node_id") or node_id)
    if declared_node != node_id:
        raise ValueError(
            f"capability resolution is for {declared_node}, not {node_id}"
        )
    if resolution.get("scope") == "activation_audit":
        raise ValueError(
            "runtime requires a current-node capability resolution"
        )
    value: dict[str, Any] = {"node_id": node_id}
    for key in _RESOLUTION_LIST_FIELDS:
        items = resolution.get(key, [])
        if not isinstance(items, list):
            raise ValueError(f"capability resolution {key} must be an array")
        semantic_items = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError(
                    f"capability resolution {key} entries must be objects"
                )
            semantic_items.append({
                field: deepcopy(item[field])
                for field in _RESOLUTION_ITEM_FIELDS
                if field in item
            })
        value[key] = semantic_items
    return value


def _reject_server_identity(value: Any, *, location: str) -> None:
    if isinstance(value, dict):
        forbidden = sorted(
            str(key)
            for key in value
            if str(key) in _SERVER_FORBIDDEN_IDENTITY_FIELDS
        )
        if forbidden:
            raise ValueError(
                f"{location} may persist descriptions, not Skill identity: "
                + ", ".join(forbidden)
            )
        for key, item in value.items():
            _reject_server_identity(
                item,
                location=f"{location}.{key}",
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_server_identity(
                item,
                location=f"{location}[{index}]",
            )


def serialize_capability_resolution(
    resolution: dict[str, Any],
    *,
    node_id: str,
) -> tuple[dict[str, Any], str, str]:
    value = normalize_capability_resolution(
        resolution,
        node_id=node_id,
    )
    serialized = orjson.dumps(
        value,
        option=orjson.OPT_SORT_KEYS,
    ).decode()
    serialized_bytes = serialized.encode()
    if len(serialized_bytes) > _MAX_RESOLUTION_BYTES:
        raise ValueError(
            "current capability resolution exceeds 4096 bytes"
        )
    semantic_hash = hashlib.sha256(serialized_bytes).hexdigest()
    return value, serialized, semantic_hash


def validate_trial_plan_hash(value: Any) -> str:
    """Validate only the opaque current TrialPlan hash projection."""
    if value in (None, ""):
        return ""
    if not isinstance(value, str):
        raise ValueError("trial_plan_hash must be a sha256 string")
    normalized = value.removeprefix("sha256:")
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef"
        for character in normalized
    ):
        raise ValueError("trial_plan_hash must be a sha256 string")
    return normalized
