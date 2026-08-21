"""Stable identities for effective grouped-strategy configurations."""

from __future__ import annotations

import hashlib
import json
from typing import Any

_PRESENTATION_KEYS = {
    "id", "strategy_id", "group_id", "group_index", "groupIndex",
    "display_name", "name", "parentId", "_expanded",
    "factor", "product_path_selection",
}


def _identity_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {
            str(key): _identity_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if key not in _PRESENTATION_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_identity_value(item) for item in value]
    for key in ("ref", "factor_ref", "owner_ref", "family_ref", "alias", "name"):
        candidate = getattr(value, key, None)
        if candidate not in (None, ""):
            return {"kind": type(value).__name__, key: str(candidate)}
    return {"kind": type(value).__name__}


def strategy_configuration_id(
    owner: dict[str, Any], settings: dict[str, Any],
) -> str:
    payload = {
        "product_path_selection_id": str(
            owner.get("product_path_selection_id") or ""
        ),
        "settings": _identity_value(settings),
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
