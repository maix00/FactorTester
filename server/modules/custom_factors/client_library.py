"""Source-free factor-library projection for embedded clients."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from hashlib import sha256
from typing import Any

from tools.cli.release.research_reporting.references.factor_formula import (
    build_factor_family_reference,
    verify_factor_reference,
)
from tools.factors.formula_identity import freeze_factor_identity

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

    families_by_identity: dict[tuple[str, str], dict[str, Any]] = {}
    for item in payload.get("families") or []:
        if not isinstance(item, dict):
            continue
        family = _family_projection(item)
        if family is not None:
            key = _family_group_key(family)
            families_by_identity[key] = {
                **families_by_identity.get(key, {}),
                **family,
            }

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in factors:
        grouped[_family_group_key(item)].append(item)
    for identity, items in sorted(grouped.items()):
        first = items[0]
        owner_username = first["owner_username"]
        family_alias = first["factor_family_alias"]
        sources = {
            str(item.get("source") or item.get("factor_kind") or "")
            .strip().lower()
            for item in items
        }
        family_source = (
            "public" if (
                "public" in sources
                or first.get("factor_owner_ref") in {"public", "__public_jobs__"}
            )
            else "custom" if "custom" in sources
            else "registered"
        )
        existing = families_by_identity.get(identity)
        if family_source == "public" and existing is None:
            # Registering parameters for a public factor creates a Factor,
            # not a user-owned FactorFamily.  Public family rows come only
            # from the authoritative public source catalog, which is merged
            # independently from own/subordinate account projections.
            continue
        family_ref = build_factor_family_reference(
            owner_ref=first["factor_owner_ref"],
            family_alias=family_alias,
            family_formula_fingerprint=first["family_formula_fingerprint"],
        )
        family = {
            "family_ref": family_ref,
            "factor_family_alias": family_alias,
            "factor_family_name": first["factor_family_name"],
            "chinese_name": first["chinese_name"],
            "description": first["description"],
            "math_expr": first["math_expr"],
            "owner_username": (
                "__public_jobs__" if family_source == "public"
                else owner_username
            ),
            "owner_alias": (
                "公共因子库" if family_source == "public"
                else first["owner_alias"]
            ),
            "factor_owner_ref": first["factor_owner_ref"],
            "family_formula_fingerprint": first[
                "family_formula_fingerprint"
            ],
            "factor_kind": family_source,
            "source": family_source,
            "has_source_definition": False,
            "factor_count": len(items),
            "categories": sorted({
                item["category"] for item in items if item["category"]
            }),
            "factor_refs": sorted({item["factor_ref"] for item in items}),
        }
        if existing is not None:
            family["params"] = existing.get("params") or []
            try:
                existing_count = max(0, int(existing.get("factor_count") or 0))
            except (TypeError, ValueError):
                existing_count = 0
            family = {
                **family,
                **existing,
                "factor_count": max(existing_count, family["factor_count"]),
                "factor_refs": sorted({
                    *family.get("factor_refs", []),
                    *existing.get("factor_refs", []),
                }),
            }
        families_by_identity[identity] = family

    families = sorted(
        families_by_identity.values(),
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


def _family_group_key(item: dict[str, Any]) -> tuple[str, str]:
    """Identify a family independently from any registered formula revision."""
    alias = _safe_text(
        item.get("factor_family_alias")
        or item.get("factor_family_name")
        or item.get("family_alias")
        or item.get("family")
    )
    source = str(item.get("source") or item.get("factor_kind") or "").lower()
    owner_ref = _safe_text(item.get("factor_owner_ref") or item.get("owner_ref"))
    owner_username = _safe_text(item.get("owner_username"))
    if source == "public" or owner_ref in {"public", "__public_jobs__"}:
        owner = "public"
    else:
        owner = owner_username or owner_ref
    return owner, alias


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
    owner_ref = _safe_text(
        item.get("factor_owner_ref") or item.get("owner_ref") or owner_username
    )
    family_fingerprint = _safe_text(item.get("family_formula_fingerprint"))
    if not owner_ref or not family_fingerprint:
        return None
    family_ref = build_factor_family_reference(
        owner_ref=owner_ref,
        family_alias=family_alias,
        family_formula_fingerprint=family_fingerprint,
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
        "resolved_math_expr": _safe_math_text(item.get("resolved_math_expr")),
        "category": category,
        "categories": sorted(set(categories)),
        "params": _params(item.get("params")),
        "owner_username": owner_username,
        "factor_owner_ref": owner_ref,
        "family_formula_fingerprint": family_fingerprint,
        "owner_alias": _safe_text(item.get("owner_alias") or owner_username),
        "owner_organization_name": _safe_text(
            item.get("owner_organization_name")
        ),
        "factor_kind": source,
        "source": source,
        "has_source_definition": True,
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
    factor_alias = _safe_text(item.get("factor_alias"))
    kind = str(item.get("source") or "").strip().lower()
    if kind not in {"custom", "public"}:
        kind = "registered"
    params = _params(item.get("params"))
    family_fingerprint = _safe_text(item.get("family_formula_fingerprint"))
    self_fingerprint = _safe_text(item.get("self_formula_fingerprint"))
    factor_ref = _safe_text(item.get("factor_ref") or item.get("target_ref"))
    verify_factor_reference(
        factor_ref,
        owner_ref=owner_ref,
        family_alias=family_alias,
        factor_alias=factor_alias,
        family_formula_fingerprint=family_fingerprint,
        self_formula_fingerprint=self_fingerprint,
    )
    frozen = freeze_factor_identity(
        owner_ref=owner_ref,
        family_alias=family_alias,
        factor_alias=factor_alias,
        family_formula_fingerprint=family_fingerprint,
        self_formula_fingerprint=self_fingerprint,
        params={
            str(value["alias"]): value.get("value")
            for value in params
            if value.get("alias")
        },
    )
    if frozen["ref"] != factor_ref:
        raise ValueError("factor projection reference does not match frozen identity")
    result = {
        **frozen,
        "factor_ref": factor_ref,
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
        "family_formula_fingerprint": family_fingerprint,
        "self_formula_fingerprint": self_fingerprint,
        "factor_params": params,
        "parameter_definitions": _params(
            item.get("parameter_definitions"), rich=True,
        ),
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
    return result


def _params(value: Any, *, rich: bool = False, depth: int = 0) -> list[dict[str, Any]]:
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
        row = {
            "alias": alias,
            "value": _safe_text(display),
            "redacted": False,
        }
        if rich:
            for key in (
                "name", "desc", "type", "input_help", "default_value",
                "value_space_desc", "input_mode",
            ):
                if item.get(key) not in (None, ""):
                    row[key] = _safe_long_text(item.get(key))
            if isinstance(item.get("options"), list):
                row["options"] = [
                    {
                        "value": _safe_text(option.get("value")),
                        "label": _safe_text(option.get("label")),
                    }
                    for option in item["options"][:128]
                    if isinstance(option, dict)
                ]
            if depth < 12 and isinstance(item.get("nested_factor"), dict):
                row["nested_factor"] = _nested_factor_projection(
                    item["nested_factor"], depth=depth + 1,
                )
        result.append(row)
    return result


def _nested_factor_projection(value: dict[str, Any], *, depth: int) -> dict[str, Any]:
    result = {
        "factor_ref": _safe_text(value.get("factor_ref") or value.get("ref")),
        "factor_alias": _safe_text(value.get("factor_alias") or value.get("alias")),
        "factor_family_alias": _safe_text(value.get("factor_family_alias")),
        "factor_family_name": _safe_text(value.get("factor_family_name")),
        "factor_owner_ref": _safe_text(
            value.get("factor_owner_ref") or value.get("owner_ref")
        ),
        "owner_username": _safe_text(value.get("owner_username")),
        "factor_kind": _safe_text(value.get("factor_kind")),
        "source": _safe_text(value.get("source")),
        "family_formula_fingerprint": _safe_text(
            value.get("family_formula_fingerprint")
        ),
        "self_formula_fingerprint": _safe_text(
            value.get("self_formula_fingerprint")
        ),
        "math_expr": _safe_math_text(value.get("math_expr")),
        "resolved_math_expr": _safe_math_text(value.get("resolved_math_expr")),
        "parameter_definitions": _params(
            value.get("parameter_definitions"), rich=True, depth=depth,
        ),
    }
    return {key: item for key, item in result.items() if item not in (None, "", [])}


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
