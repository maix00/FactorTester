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
_MAX_LONG_TEXT_BYTES = 4096


def build_client_library_projection(
    payload: dict[str, Any],
    *,
    principal: str,
) -> dict[str, Any]:
    """Return safe family templates and registered factors.

    ``families`` may contain source templates with no registered members.
    Only rows supplied through ``factors`` are treated as parameterized
    factors owned by an account.
    """
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

    families_by_ref: dict[str, dict[str, Any]] = {}
    for item in payload.get("families") or []:
        if not isinstance(item, dict):
            continue
        family = _family_projection(item)
        if family is not None:
            families_by_ref[family["family_ref"]] = family

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in factors:
        grouped[
            (item["owner_username"], item["factor_family_alias"])
        ].append(item)
    for (owner_username, family_alias), items in sorted(grouped.items()):
        first = items[0]
        sources = {
            str(item.get("source") or item.get("factor_kind") or "")
            .strip().lower()
            for item in items
        }
        family_source = (
            "public" if "public" in sources
            else "custom" if "custom" in sources
            else "registered"
        )
        family_ref = _ref(
            "factor-family",
            owner_username,
            family_alias,
        )
        family = {
            "family_ref": family_ref,
            "factor_family_alias": family_alias,
            "factor_family_name": first["factor_family_name"],
            "chinese_name": first["chinese_name"],
            "description": first["description"],
            "math_expr": first["math_expr"],
            "owner_username": owner_username,
            "owner_alias": first["owner_alias"],
            "factor_kind": family_source,
            "source": family_source,
            "factor_count": len(items),
            "categories": sorted({
                item["category"] for item in items if item["category"]
            }),
            "factor_refs": sorted({item["factor_ref"] for item in items}),
        }
        existing = families_by_ref.get(family_ref)
        if existing is not None:
            family["params"] = existing.get("params") or []
            try:
                existing_count = max(0, int(existing.get("factor_count") or 0))
            except (TypeError, ValueError):
                existing_count = 0
            family["factor_count"] = max(existing_count, family["factor_count"])
        families_by_ref[family_ref] = {**(existing or {}), **family}

    families = sorted(
        families_by_ref.values(),
        key=lambda item: (
            item["factor_family_alias"],
            item["owner_alias"],
            item["family_ref"],
        ),
    )

    projection = {
        "schema_version": 2,
        "mode": "embedded_read_only_library",
        "principal": _safe_text(principal),
        "factors": factors,
        "families": families,
        "categories": sorted({
            category
            for item in factors + families
            for category in (
                [item["category"]] if item.get("category") else []
            ) + list(item.get("categories") or [])
            if category
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


def _family_projection(item: dict[str, Any]) -> dict[str, Any] | None:
    """Sanitize a family template without manufacturing a factor member."""
    family_alias = _safe_text(
        item.get("factor_family_alias")
        or item.get("factor_family_name")
        or item.get("family_alias")
        or item.get("family")
    )
    if not family_alias:
        return None
    owner_username = _safe_text(item.get("owner_username"))
    family_ref = _safe_text(item.get("family_ref")) or _ref(
        "factor-family", owner_username, family_alias,
    )
    source = str(
        item.get("source") or item.get("factor_kind") or "registered"
    ).strip().lower()
    if source not in {"custom", "public", "registered"}:
        source = "registered"
    categories = [
        _safe_text(value)
        for value in item.get("categories") or []
        if _safe_text(value)
    ]
    category = _safe_text(item.get("category"))
    if category and category not in categories:
        categories.append(category)
    try:
        factor_count = max(0, int(item.get("factor_count") or 0))
    except (TypeError, ValueError):
        factor_count = 0
    factor_refs = [
        _safe_text(value)
        for value in item.get("factor_refs") or []
        if _safe_text(value)
    ]
    return {
        "family_ref": family_ref,
        "factor_family_alias": family_alias,
        "factor_family_name": _safe_text(
            item.get("factor_family_name") or family_alias
        ),
        "chinese_name": _safe_text(item.get("chinese_name")),
        "description": _safe_long_text(item.get("description")),
        "math_expr": _safe_math_text(item.get("math_expr")),
        "category": category,
        "categories": sorted(set(categories)),
        "params": _params(item.get("params")),
        "owner_username": owner_username,
        "owner_alias": _safe_text(item.get("owner_alias") or owner_username),
        "owner_organization_name": _safe_text(
            item.get("owner_organization_name")
        ),
        "factor_kind": source,
        "source": source,
        "factor_count": factor_count,
        "factor_refs": sorted(set(factor_refs)),
        "updated_at": _safe_text(item.get("updated_at")),
    }


def _factor_projection(item: dict[str, Any]) -> dict[str, Any]:
    owner = _safe_text(item.get("owner_username"))
    owner_ref = _safe_text(
        item.get("factor_owner_ref") or item.get("owner_ref") or owner
    )
    family_alias = _safe_text(
        item.get("factor_family_alias")
        or item.get("factor_family_name")
    )
    family_ref = _safe_text(
        item.get("factor_family_ref") or item.get("family_ref")
    ) or _ref("factor-family", owner, family_alias)
    factor_alias = _safe_text(item.get("factor_alias"))
    kind = str(item.get("source") or "").strip().lower()
    if kind not in {"custom", "public"}:
        kind = "registered"
    params = _params(item.get("params"))
    result = {
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
        "description": _safe_long_text(item.get("description")),
        "math_expr": _safe_math_text(item.get("math_expr")),
        "category": _safe_text(item.get("category")),
        "factor_kind": kind,
        "params": params,
        "factor_owner_ref": owner_ref,
        "factor_family_ref": family_ref,
        "factor_params": params,
        "params_count": len(params),
        "owner_username": owner,
        "owner_alias": _safe_text(item.get("owner_alias") or owner),
        "owner_organization_name": _safe_text(
            item.get("owner_organization_name")
        ),
        "scope_key": _safe_text(
            item.get("scope_key") or item.get("product_group")
        ),
        "product_group": _safe_text(item.get("product_group")),
        "updated_at": _safe_text(item.get("updated_at")),
    }
    commit = _safe_text(item.get("factor_git_commit") or item.get("git_commit"))
    if commit:
        # A present commit means this factor is pinned to a historical family
        # source. Do not serialize an empty marker for current/latest factors.
        result["factor_git_commit"] = commit
    return result


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


def _safe_long_text(value: Any) -> str:
    text = str(value or "").strip()
    if _looks_like_local_path(text):
        return ""
    raw = text.encode()
    if len(raw) <= _MAX_LONG_TEXT_BYTES:
        return text
    return raw[: _MAX_LONG_TEXT_BYTES - 3].decode(errors="ignore") + "..."


def _safe_math_text(value: Any) -> str:
    text = str(value or "").strip()
    lowered = text.lower()
    if "file://" in lowered or "/users/" in lowered or "/opt/" in lowered:
        return ""
    raw = text.encode()
    if len(raw) <= _MAX_LONG_TEXT_BYTES:
        return text
    return raw[: _MAX_LONG_TEXT_BYTES - 3].decode(errors="ignore") + "..."


def _looks_like_local_path(value: str) -> bool:
    return bool(_LOCAL_PATH.search(str(value or "").strip()))


def _ref(kind: str, *parts: str) -> str:
    identity = "\x1f".join(str(part) for part in parts)
    return f"{kind}:sha256:{sha256(identity.encode()).hexdigest()}"
