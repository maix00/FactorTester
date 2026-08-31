"""Shared routing helpers for the canonical product-library API."""

from __future__ import annotations

PRODUCT_LIBRARY_PREFIX = "/api/product-library/"
MARKET_DATA_PREFIX = "/api/market-data/"


def product_library_source_ids(
    query: dict[str, list[str]],
) -> tuple[str, ...]:
    """Resolve repeated or comma-separated data-source filters."""
    from server.services.product_catalog_projection import (
        catalog_source_ids as default_source_ids,
    )
    from server.services.product_catalog_projection import normalize_source_ids

    requested = [
        item.strip()
        for value in query.get("data_source", [])
        for item in str(value).split(",")
        if item.strip()
    ]
    return normalize_source_ids(requested) if requested else default_source_ids()


def product_library_page(
    rows: list[dict], query: dict[str, list[str]],
) -> dict[str, object]:
    """Filter and bound a product search response for lazy clients."""
    search = str(query.get("query", [""])[0] or "").strip().casefold()
    if search:
        rows = [
            row for row in rows
            if search in " ".join(
                str(row.get(key) or "")
                for key in (
                    "name", "code", "desc", "description", "exchange",
                    "product_path", "source_ids",
                )
            ).casefold()
        ]
    try:
        page = max(1, int(query.get("page", ["1"])[0] or 1))
        limit = min(100, max(1, int(query.get("limit", ["25"])[0] or 25)))
    except (TypeError, ValueError) as exc:
        raise ValueError("产品列表分页参数无效") from exc
    total = len(rows)
    total_pages = max(1, (total + limit - 1) // limit)
    offset = (page - 1) * limit
    return {
        "products": rows[offset:offset + limit],
        "page": page,
        "limit": limit,
        "total": total,
        "total_pages": total_pages,
        "has_more": page < total_pages,
    }


__all__ = [
    "MARKET_DATA_PREFIX",
    "PRODUCT_LIBRARY_PREFIX",
    "product_library_page",
    "product_library_source_ids",
]

