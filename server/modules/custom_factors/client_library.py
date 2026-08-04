"""Source-free factor-library projection for embedded clients."""

from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json
import re
from typing import Any


_LOCAL_PATH = re.compile(
    r"(^~[/\\])|(^[/\\])|(^[A-Za-z]:[/\\])|(file://)"
    r"|(\.py(?:$|[^A-Za-z0-9_]))",
    re.IGNORECASE,
)
_MAX_TEXT_BYTES = 256


def build_client_library_projection(
    payload: dict[str, Any],
    *,
    principal: str,
) -> dict[str, Any]:
    """Return registered factor metadata without source or formula fields."""
    projected = [
        _factor_projection(item)
        for item in payload.get("factors") or []
        if isinstance(item, dict)
    ]
    projected = [item for item in projected if item["factor_alias"]]
    factors_by_ref: dict[str, dict[str, Any]] = {}
    for item in projected:
        if item["factor_ref"] not in factors_by_ref:
            factors_by_ref[item["factor_ref"]] = item
    factors = list(factors_by_ref.values())
    factors.sort(key=lambda item: (
        item["factor_family_alias"],
        item["owner_alias"],
        item["factor_alias"],
    ))

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in factors:
        grouped[
            (item["owner_username"], item["factor_family_alias"])
        ].append(item)
    families = []
    for (owner_username, family_alias), items in sorted(grouped.items()):
        first = items[0]
        family_ref = _ref(
            "factor-family",
            owner_username,
            family_alias,
        )
        families.append({
            "family_ref": family_ref,
            "factor_family_alias": family_alias,
            "factor_family_name": first["factor_family_name"],
            "chinese_name": first["chinese_name"],
            "owner_username": owner_username,
            "owner_alias": first["owner_alias"],
            "factor_count": len(items),
            "categories": sorted({
                item["category"] for item in items if item["category"]
            }),
            "factor_refs": sorted({item["factor_ref"] for item in items}),
        })

    projection = {
        "schema_version": 2,
        "mode": "embedded_read_only_library",
        "principal": _safe_text(principal),
        "factors": factors,
        "families": families,
        "categories": sorted({
            item["category"] for item in factors if item["category"]
        }),
        "omitted_error_count": len(payload.get("errors") or []),
    }
    encoded = json.dumps(
        projection,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return {
        **projection,
        "projection_hash": sha256(encoded).hexdigest(),
    }


def _factor_projection(item: dict[str, Any]) -> dict[str, Any]:
    owner = _safe_text(item.get("owner_username"))
    family_alias = _safe_text(
        item.get("factor_family_alias")
        or item.get("factor_family_name")
    )
    factor_alias = _safe_text(item.get("factor_alias"))
    kind = str(item.get("source") or "").strip().lower()
    if kind not in {"custom", "public"}:
        kind = "registered"
    params = _params(item.get("params"))
    return {
        "factor_ref": _ref(
            "factor",
            owner,
            family_alias,
            factor_alias,
        ),
        "factor_alias": factor_alias,
        "factor_family_alias": family_alias,
        "factor_family_name": _safe_text(
            item.get("factor_family_name") or family_alias
        ),
        "chinese_name": _safe_text(item.get("chinese_name")),
        "category": _safe_text(item.get("category")),
        "factor_kind": kind,
        "params": params,
        "params_count": len(params),
        "owner_username": owner,
        "owner_alias": _safe_text(item.get("owner_alias") or owner),
        "owner_organization_name": _safe_text(
            item.get("owner_organization_name")
        ),
        "updated_at": _safe_text(item.get("updated_at")),
    }


def _params(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value[:64]:
        if not isinstance(item, dict):
            continue
        alias = _safe_text(item.get("alias"))
        if not alias:
            continue
        raw_value = item.get("value")
        display = "" if raw_value is None else str(raw_value)
        if _looks_like_local_path(display):
            result.append({
                "alias": alias,
                "value": None,
                "redacted": True,
            })
            continue
        result.append({
            "alias": alias,
            "value": _safe_text(display),
            "redacted": False,
        })
    return result


def _safe_text(value: Any) -> str:
    text = str(value or "").strip()
    if _looks_like_local_path(text):
        return ""
    raw = text.encode()
    if len(raw) <= _MAX_TEXT_BYTES:
        return text
    return raw[: _MAX_TEXT_BYTES - 3].decode(errors="ignore") + "..."


def _looks_like_local_path(value: str) -> bool:
    return bool(_LOCAL_PATH.search(str(value or "").strip()))


def _ref(kind: str, *parts: str) -> str:
    identity = "\x1f".join(str(part) for part in parts)
    return f"{kind}:sha256:{sha256(identity.encode()).hexdigest()}"
