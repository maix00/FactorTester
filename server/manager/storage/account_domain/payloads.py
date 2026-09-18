"""Stable, bounded metadata payloads for the account-domain sync seam."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .local import ENTITY_TYPES


_PRIVATE_KEY_PARTS = (
    "password", "password_hash", "salt", "token", "secret", "private_key",
    "workspace_root", "worktree_path", "research_root", "source_code",
    "content_base64", "raw_b64", "absolute_path", "local_path",
    "report_path", "artifact_path", "file_path",
)
MAX_PAYLOAD_BYTES = 512 * 1024


class PayloadTooLarge(ValueError):
    """携带超限字段清单，便于上层把诊断信息透传给调用方。"""

    def __init__(self, byte_length: int, field_sizes: list[dict[str, object]]) -> None:
        self.byte_length = int(byte_length)
        self.field_sizes = field_sizes
        summary = ", ".join(f"{item['field']}={item['bytes']}" for item in field_sizes[:6])
        super().__init__(f"account-domain metadata payload is too large ({byte_length} bytes): {summary}")


def validate_entity(entity_type: str, entity_id: str) -> tuple[str, str]:
    kind = str(entity_type or "").strip()
    identifier = str(entity_id or "").strip()
    if kind not in ENTITY_TYPES:
        raise ValueError("unsupported account-domain entity type")
    if not identifier or len(identifier) > 512:
        raise ValueError("account-domain entity id is invalid")
    return kind, identifier


def public_payload(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Drop credentials, local paths, and raw bytes before persistence."""
    result = _clean(dict(value or {}), depth=0)
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        # 定位超限字段：把逐字段大小与 resolved_factors 形状带进异常，供上层透传。
        sizes = []
        for key, value in result.items():
            size = len(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
            sizes.append({"field": key, "bytes": size})
        sizes.sort(key=lambda item: item["bytes"], reverse=True)
        raise PayloadTooLarge(len(encoded.encode("utf-8")), sizes)
    return result


def _clean(value: Any, *, depth: int) -> Any:
    if depth > 64:
        raise ValueError("account-domain metadata nesting is too deep")
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            lowered = name.lower()
            if any(part in lowered for part in _PRIVATE_KEY_PARTS):
                continue
            output[name] = _clean(item, depth=depth + 1)
        return output
    if isinstance(value, (list, tuple)):
        return [_clean(item, depth=depth + 1) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
