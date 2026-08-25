"""Merge source-free factor catalog projections from Manager mirrors."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any


VISITOR_PRINCIPAL = "__public_jobs__"


def _family_identity(item: dict[str, Any]) -> tuple[str, str]:
    alias = str(
        item.get("factor_family_alias")
        or item.get("factor_family_name")
        or ""
    ).strip()
    source = str(item.get("source") or item.get("factor_kind") or "").lower()
    owner_ref = str(item.get("factor_owner_ref") or "").strip()
    owner = str(item.get("owner_username") or owner_ref).strip()
    if source == "public" or owner_ref in {"public", VISITOR_PRINCIPAL}:
        owner = "public"
    return owner, alias


def _merge_family(
    existing: dict[str, Any] | None,
    incoming: dict[str, Any],
) -> dict[str, Any]:
    if existing is None:
        return dict(incoming)
    existing_source = bool(existing.get("has_source_definition"))
    incoming_source = bool(incoming.get("has_source_definition"))
    if incoming_source or not existing_source:
        primary, secondary = incoming, existing
    else:
        primary, secondary = existing, incoming
    merged = {**secondary, **primary}
    for field in (
        "chinese_name", "description", "math_expr", "category", "params",
        "family_formula_fingerprint", "updated_at",
    ):
        if merged.get(field) in (None, "", []):
            merged[field] = secondary.get(field)
    refs = sorted({
        str(value).strip()
        for row in (existing, incoming)
        for value in row.get("factor_refs") or []
        if str(value).strip()
    })
    categories = sorted({
        str(value).strip()
        for row in (existing, incoming)
        for value in row.get("categories") or []
        if str(value).strip()
    })
    counts = []
    for row in (existing, incoming):
        try:
            counts.append(max(0, int(row.get("factor_count") or 0)))
        except (TypeError, ValueError):
            pass
    merged["factor_refs"] = refs
    merged["categories"] = categories
    merged["factor_count"] = max([len(refs), *counts], default=0)
    return merged


def merge_factor_library_projections(
    values: list[dict[str, Any]], *, principal: str,
) -> dict[str, Any]:
    """Merge projections while preserving their already-frozen stable refs."""
    factors: dict[str, dict[str, Any]] = {}
    families: dict[tuple[str, str], dict[str, Any]] = {}
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
            ref = str(item.get("family_ref") or "").strip()
            if ref:
                key = _family_identity(item)
                families[key] = _merge_family(families.get(key), item)
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
