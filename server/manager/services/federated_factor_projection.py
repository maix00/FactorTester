"""Merge source-free factor catalog projections from Manager mirrors."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any


VISITOR_PRINCIPAL = "__public_jobs__"


def _legacy_public_factor(item: dict[str, Any]) -> bool:
    return str(item.get("owner_username") or "").strip() == VISITOR_PRINCIPAL


def _legacy_public_family(item: dict[str, Any]) -> dict[str, Any]:
    owner = VISITOR_PRINCIPAL
    family_alias = str(
        item.get("factor_family_alias") or item.get("factor_family_name") or ""
    ).strip()
    family_ref = str(item.get("family_ref") or "").strip()
    if not family_ref:
        family_ref = "factor-family:sha256:" + sha256(
            f"{owner}\x1f{family_alias}".encode()
        ).hexdigest()
    return {
        "family_ref": family_ref,
        "factor_family_alias": family_alias,
        "factor_family_name": item.get("factor_family_name") or family_alias,
        "chinese_name": item.get("chinese_name") or "",
        "description": item.get("description") or "",
        "math_expr": item.get("math_expr") or "",
        "category": item.get("category") or "",
        "categories": list(item.get("categories") or []),
        "params": list(item.get("params") or []),
        "owner_username": owner,
        "owner_alias": item.get("owner_alias") or "公共因子库",
        "factor_kind": "public",
        "source": "public",
        "factor_count": 0,
        "factor_refs": [],
        "updated_at": item.get("updated_at") or "",
    }


def merge_factor_library_projections(
    values: list[dict[str, Any]], *, principal: str,
) -> dict[str, Any]:
    """Merge projections while preserving their already-frozen stable refs."""
    factors: dict[str, dict[str, Any]] = {}
    families: dict[str, dict[str, Any]] = {}
    categories: set[str] = set()
    errors: list[Any] = []
    schema_version = 1
    for value in values:
        if not isinstance(value, dict):
            continue
        try:
            schema_version = max(schema_version, int(value.get("schema_version") or 1))
        except (TypeError, ValueError):
            pass
        for item in value.get("factors") or []:
            if not isinstance(item, dict):
                continue
            if _legacy_public_factor(item):
                family = _legacy_public_family(item)
                if family["factor_family_alias"]:
                    families.setdefault(family["family_ref"], family)
                continue
            ref = str(item.get("factor_ref") or "").strip()
            if ref:
                factors.setdefault(ref, dict(item))
            category = str(item.get("category") or "").strip()
            if category:
                categories.add(category)
        for item in value.get("families") or []:
            if not isinstance(item, dict):
                continue
            item = dict(item)
            if _legacy_public_factor(item):
                item["factor_count"] = 0
                item["factor_refs"] = []
            ref = str(item.get("family_ref") or "").strip()
            if ref:
                families[ref] = {**families.get(ref, {}), **item}
            for category in item.get("categories") or []:
                category = str(category or "").strip()
                if category:
                    categories.add(category)
        errors.extend(item for item in value.get("errors") or [])
    factor_values = sorted(
        factors.values(),
        key=lambda item: (
            str(item.get("factor_family_alias") or ""),
            str(item.get("owner_alias") or ""),
            str(item.get("factor_alias") or ""),
            str(item.get("factor_ref") or ""),
        ),
    )
    family_values = sorted(
        families.values(),
        key=lambda item: (
            str(item.get("factor_family_alias") or ""),
            str(item.get("owner_alias") or ""),
            str(item.get("family_ref") or ""),
        ),
    )
    projection = {
        "schema_version": schema_version,
        "mode": "embedded_read_only_library",
        "principal": str(principal or ""),
        "factors": factor_values,
        "families": family_values,
        "categories": sorted(categories),
        "omitted_error_count": len(errors),
    }
    encoded = json.dumps(
        projection, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()
    return {**projection, "projection_hash": sha256(encoded).hexdigest()}
