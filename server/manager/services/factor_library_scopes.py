"""Scope projections for the FactorTester factor-family catalog.

The catalog has three deliberately separate visibility scopes.  Keeping the
scope envelope here lets the local Manager, federation endpoint, and web
client share the same contract while retaining the older flat ``factors`` and
``families`` fields for detail pages and older clients.
"""

from __future__ import annotations

from typing import Any


PUBLIC_SCOPE = "public"
MINE_SCOPE = "mine"
SUBORDINATES_SCOPE = "subordinates"
FAMILY_SCOPES = (PUBLIC_SCOPE, MINE_SCOPE, SUBORDINATES_SCOPE)
PUBLIC_PRINCIPAL = "__public_jobs__"


def empty_factor_projection(principal: str = "") -> dict[str, Any]:
    """Return an empty safe projection for a missing visibility scope."""
    return {
        "schema_version": 2,
        "mode": "embedded_read_only_library",
        "principal": str(principal or ""),
        "factors": [],
        "families": [],
        "categories": [],
        "errors": [],
        "omitted_error_count": 0,
    }


def _projection(value: Any, *, factors: list[dict[str, Any]], families: list[dict[str, Any]]) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    categories = {
        str(item.get("category") or "").strip()
        for item in factors + families
        if isinstance(item, dict) and str(item.get("category") or "").strip()
    }
    for family in families:
        if isinstance(family, dict):
            categories.update(
                str(item or "").strip()
                for item in family.get("categories") or []
                if str(item or "").strip()
            )
    return {
        "schema_version": source.get("schema_version") or 2,
        "mode": source.get("mode") or "embedded_read_only_library",
        "principal": str(source.get("principal") or ""),
        "factors": [dict(item) for item in factors],
        "families": [dict(item) for item in families],
        "categories": sorted(categories),
        "errors": list(source.get("errors") or []),
        "omitted_error_count": int(source.get("omitted_error_count") or 0),
    }


def _is_public(item: dict[str, Any]) -> bool:
    owner = str(item.get("owner_username") or "").strip()
    if owner == PUBLIC_PRINCIPAL:
        return True
    # A user's registered parameter configuration may use a public source;
    # ownership still places that configured family in the user's own tab.
    if owner:
        return False
    kind = str(item.get("factor_kind") or item.get("source") or "").strip().lower()
    return kind == PUBLIC_SCOPE


def _scope_for(item: dict[str, Any], principal: str) -> str:
    if _is_public(item):
        return PUBLIC_SCOPE
    if str(item.get("owner_username") or "") == str(principal or ""):
        return MINE_SCOPE
    return SUBORDINATES_SCOPE


def split_factor_library_scopes(
    value: dict[str, Any] | None,
    *,
    principal: str,
    visitor: bool = False,
) -> dict[str, dict[str, Any]]:
    """Read the new scoped envelope, or safely classify a legacy flat one."""
    source = value if isinstance(value, dict) else {}
    raw_scopes = source.get("family_scopes") or source.get("family_tabs")
    if isinstance(raw_scopes, dict):
        result = {
            scope: _projection(
                raw_scopes.get(scope),
                factors=list((raw_scopes.get(scope) or {}).get("factors") or [])
                if isinstance(raw_scopes.get(scope), dict) else [],
                families=list((raw_scopes.get(scope) or {}).get("families") or [])
                if isinstance(raw_scopes.get(scope), dict) else [],
            )
            for scope in FAMILY_SCOPES
            if isinstance(raw_scopes.get(scope), dict)
        }
        if result:
            if visitor:
                return {PUBLIC_SCOPE: result.get(PUBLIC_SCOPE, empty_factor_projection(principal))}
            return result

    factor_buckets: dict[str, list[dict[str, Any]]] = {
        scope: [] for scope in FAMILY_SCOPES
    }
    family_buckets: dict[str, list[dict[str, Any]]] = {
        scope: [] for scope in FAMILY_SCOPES
    }
    for item in source.get("factors") or []:
        if isinstance(item, dict):
            scope = _scope_for(item, principal)
            if not visitor or scope == PUBLIC_SCOPE:
                factor_buckets[scope].append(dict(item))
    for item in source.get("families") or []:
        if isinstance(item, dict):
            scope = _scope_for(item, principal)
            if not visitor or scope == PUBLIC_SCOPE:
                family_buckets[scope].append(dict(item))

    scopes = {
        scope: _projection(
            source,
            factors=factor_buckets[scope],
            families=family_buckets[scope],
        )
        for scope in FAMILY_SCOPES
        if not visitor or scope == PUBLIC_SCOPE
    }
    return scopes


def compose_factor_library_scopes(
    scopes: dict[str, dict[str, Any]], *, principal: str,
) -> dict[str, Any]:
    """Create a response with scoped data and backward-compatible flat data."""
    normalized = {
        scope: _projection(
            scopes.get(scope),
            factors=list((scopes.get(scope) or {}).get("factors") or [])
            if isinstance(scopes.get(scope), dict) else [],
            families=list((scopes.get(scope) or {}).get("families") or [])
            if isinstance(scopes.get(scope), dict) else [],
        )
        for scope in FAMILY_SCOPES
        if isinstance(scopes.get(scope), dict)
    }
    factors = [item for value in normalized.values() for item in value["factors"]]
    families = [item for value in normalized.values() for item in value["families"]]
    errors = [item for value in normalized.values() for item in value.get("errors") or []]
    categories = sorted({
        str(item.get("category") or "").strip()
        for item in factors
        if isinstance(item, dict) and str(item.get("category") or "").strip()
    })
    return {
        "schema_version": 2,
        "mode": "embedded_read_only_library",
        "principal": str(principal or ""),
        "family_scopes": normalized,
        "factors": factors,
        "families": families,
        "categories": categories,
        "errors": errors,
        "omitted_error_count": len(errors),
    }
