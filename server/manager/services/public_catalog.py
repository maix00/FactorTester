"""Public projections for visitor-mode factor and product catalogs."""

from __future__ import annotations

from typing import Any


PUBLIC_VISITOR_PRINCIPAL = "__public_jobs__"


class VisitorCatalogAccessError(ValueError):
    """A visitor requested data owned only by an internal node."""

    status = 403


def visitor_source_descriptors(
    descriptors: list[dict[str, object]] | tuple[dict[str, object], ...],
    *,
    local_server_id: str,
) -> list[dict[str, object]]:
    """Annotate every source without hiding internal-only providers.

    ``visitor_data_accessible`` is deliberately stricter than visibility:
    source metadata may be shown when a public peer provides it, but this
    Manager may only serve bytes from a public service it owns locally.
    """
    result: list[dict[str, object]] = []
    for descriptor in descriptors:
        if not isinstance(descriptor, dict):
            continue
        value = dict(descriptor)
        providers = [
            item for item in (value.get("server_providers") or [])
            if isinstance(item, dict)
        ]
        public_providers = [
            item for item in providers
            if bool(item.get("online")) and bool(item.get("public_server"))
        ]
        local_public = any(
            str(item.get("server_id") or "") == str(local_server_id)
            for item in public_providers
        )
        value.update({
            "visitor_visible": True,
            "visitor_data_accessible": local_public,
            "visitor_public_provider_count": len(public_providers),
            "visitor_access_reason": (
                "local_public_provider" if local_public
                else "public_peer_provider" if public_providers
                else "internal_only"
            ),
        })
        result.append(value)
    return result


def visitor_local_source_ids(
    descriptors: list[dict[str, object]],
) -> tuple[str, ...]:
    """Return source IDs whose data can be served by this public Manager."""
    return tuple(dict.fromkeys(
        str(item.get("id") or "").strip()
        for item in descriptors
        if item.get("visitor_data_accessible")
        and str(item.get("id") or "").strip()
    ))


def requested_source_ids(query: dict[str, list[str]]) -> tuple[str, ...]:
    """Parse source filters without consulting the local source registry."""
    return tuple(dict.fromkeys(
        item.strip()
        for value in query.get("data_source", [])
        for item in str(value).split(",")
        if item.strip()
    ))


def select_visitor_source_ids(
    query: dict[str, list[str]],
    descriptors: list[dict[str, object]],
) -> tuple[str, ...]:
    """Select local public sources and reject internal-only requests."""
    available = set(visitor_local_source_ids(descriptors))
    known = {
        str(item.get("id") or "").strip()
        for item in descriptors
        if str(item.get("id") or "").strip()
    }
    requested = requested_source_ids(query)
    if not requested:
        return tuple(sorted(available))
    unknown = sorted(set(requested) - known)
    if unknown:
        raise VisitorCatalogAccessError(
            "未知产品数据源: " + ", ".join(unknown)
        )
    denied = sorted(set(requested) - available)
    if denied:
        raise VisitorCatalogAccessError(
            "访客模式只能获取公网 Manager 本机提供的数据源: "
            + ", ".join(denied)
        )
    return tuple(requested)


def filter_product_rows(
    rows: list[dict[str, Any]],
    source_ids: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Filter local product metadata while making an empty selection safe."""
    selected = set(source_ids)
    if not selected:
        return []
    return [
        dict(row) for row in rows
        if selected.intersection(
            str(item).strip() for item in (row.get("source_ids") or [])
        )
    ]


def ensure_visitor_product_access(
    product: dict[str, Any] | None,
    source_ids: tuple[str, ...],
) -> dict[str, Any]:
    """Return one product or raise without leaking internal-only data."""
    if not product or not set(source_ids).intersection(
        str(item).strip() for item in (product.get("source_ids") or [])
    ):
        raise VisitorCatalogAccessError(
            "访客模式不能获取内网服务器独占的产品数据"
        )
    return product


def public_factor_library() -> dict[str, Any]:
    """Return public family templates, never pretend they are user factors."""
    from server.modules.custom_factors.catalog import list_public_factors
    from server.modules.custom_factors.client_library import (
        build_client_library_projection,
    )

    families: list[dict[str, Any]] = []
    local = {str(item.get("id") or item.get("name") or ""): item for item in list_public_factors()}
    # Source providers advertise visible identity independently from resident bytes.
    import json
    import sqlite3
    import settings as Settings
    from tools.data.sqlite.db import connect_sqlite
    try:
        with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
            manifests = conn.execute(
                "SELECT payload_json FROM account_domain_entities WHERE principal='__public__' "
                "AND entity_type='factor_source' AND deleted=0 ORDER BY remote_revision DESC, updated_at DESC"
            ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc):
            raise
        manifests = []
    from tools.data.sqlite.factor_family_heads import legacy_source_manifests
    providers = ({"principal": "__public__", "payload": json.loads(row[0])}
                 for row in manifests)
    for payload in legacy_source_manifests(providers, "public", ""):
        alias = str(payload["factor_id"]).strip()
        current = local.get(alias)
        if current is None or (not current.get("family_formula_fingerprint") and payload.get("family_formula_fingerprint")):
            summary = payload.get("catalog") or payload
            local[alias] = {**summary, "id": alias, "name": payload.get("factor_name") or alias,
                            "family_formula_fingerprint": payload.get("family_formula_fingerprint") or ""}
    for item in local.values():
        alias = str(item.get("name") or item.get("id") or "").strip()
        if not alias:
            continue
        # A public source-registry row represents one FactorFamily.  Direct
        # subclasses commonly report the generic Python base name
        # ``FactorFamily``; using that value would collapse every public row
        # into one family in the client projection.  The registry ID is the
        # stable family identity, while the class name remains its display
        # name.
        family = str(item.get("id") or item.get("factor_family") or alias).strip()
        family_name = str(item.get("name") or family).strip()
        families.append({
            "factor_family_alias": family,
            "factor_family_name": family_name,
            "chinese_name": item.get("chinese_name") or "",
            "description": item.get("description") or "",
            "math_expr": item.get("math_expr") or "",
            "category": item.get("category") or "",
            "categories": [item.get("category")] if item.get("category") else [],
            "params": item.get("params") or [],
            "source": "public",
            "factor_kind": "public",
            "owner_username": PUBLIC_VISITOR_PRINCIPAL,
            "owner_alias": "公共因子库",
            "family_formula_fingerprint": item.get(
                "family_formula_fingerprint"
            ) or "",
            "updated_at": item.get("updated_at") or "",
        })
    return build_client_library_projection(
        {"factors": [], "families": families, "errors": []},
        principal=PUBLIC_VISITOR_PRINCIPAL,
    )
