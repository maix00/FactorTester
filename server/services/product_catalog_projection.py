"""Source-owned projections for the Manager product catalog.

The Manager catalog is independent from any backtest service port.  It reads
the registered product and market-data objects in the current installation so
Web and embedded clients do not have to infer bundles from display strings.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Iterable

from sources.registry import load_all_sources
from tools.data.providers import DataProviderProductTS, DataProviderProductTSBundle
from tools.products.classifier_paths import classifier_class_path, classifier_object_path


def _text(value: Any) -> str:
    return str(getattr(value, "name", value) or "")


def _concrete_members(source: Any) -> tuple[Any, ...]:
    if isinstance(source, DataProviderProductTSBundle):
        return tuple(source.members)
    return (source,)


def _contains(source: Any, product: Any) -> bool:
    try:
        return bool(product in source)
    except Exception:
        return False


def _available_products(source: Any, products: Iterable[Any]) -> tuple[Any, ...]:
    members = _concrete_members(source)
    return tuple(
        product for product in products
        if any(_contains(member, product) for member in members)
    )


def _frequency(source: Any) -> str:
    value = getattr(source, "freq", None)
    return _text(value)


def _member_descriptor(member: Any, products: tuple[Any, ...]) -> dict[str, Any]:
    available = _available_products(member, products)
    return {
        "id": str(getattr(member, "key", "")),
        "label": str(getattr(member, "label", "") or getattr(member, "key", "")),
        "frequency": _frequency(member),
        "timezone": str(getattr(member, "timezone", "") or ""),
        "time_columns": dict(getattr(member, "time_cols_mapping", {}) or {}),
        "data_columns": dict(getattr(member, "data_cols_mapping", {}) or {}),
        "product_count": len(available),
    }


@lru_cache(maxsize=2)
def product_source_descriptors(origin: str = "server") -> tuple[dict[str, Any], ...]:
    """Return actual registered bundles and unbundled providers.

    ``origin`` is presentation metadata only: on a server the registered
    filesystem/API providers are server-owned; in the packaged client the same
    registry describes client-local providers.
    """
    load_all_sources()
    from server.modules.shared.price_services import (
        available_product_categories,
        cached_products,
    )

    source_origin = "local" if str(origin).lower() == "local" else "server"
    products = tuple(cached_products())
    all_sources = tuple(DataProviderProductTS.all())
    bundles = tuple(
        source for source in all_sources
        if isinstance(source, DataProviderProductTSBundle)
    )
    bundled_member_ids = {
        id(member) for bundle in bundles for member in bundle.members
    }
    visible = (*bundles, *(
        source for source in all_sources
        if not isinstance(source, DataProviderProductTSBundle)
        and id(source) not in bundled_member_ids
    ))
    categories = available_product_categories()
    result: list[dict[str, Any]] = []
    for source in visible:
        members = tuple(
            _member_descriptor(member, products)
            for member in _concrete_members(source)
        )
        available = _available_products(source, products)
        frequencies = sorted({
            member["frequency"] for member in members if member["frequency"]
        })
        result.append({
            "id": str(getattr(source, "key", "")),
            "source_ref": f"data-source:{source_origin}:{getattr(source, 'key', '')}",
            "source_name": str(
                getattr(source, "label", "") or getattr(source, "key", "")
            ),
            "source_kind": source_origin,
            "provider_kind": (
                "bundle" if isinstance(source, DataProviderProductTSBundle)
                else "provider"
            ),
            "bundle_id": str(getattr(source, "key", "")),
            "bundle_name": str(
                getattr(source, "label", "") or getattr(source, "key", "")
            ),
            "server_provided": source_origin == "server",
            "members": list(members),
            "product_paths": sorted({
                classifier_class_path(type(product)) for product in available
            }),
            "categories": categories,
            "data_modes": [{
                "id": "historical", "title_zh": "历史数据", "available": True,
            }],
            "availability": {
                "status": "ready" if available else "empty",
                "product_count": len(available),
                "frequency_names": frequencies,
            },
        })
    return tuple(result)


@lru_cache(maxsize=1)
def catalog_product_records() -> tuple[dict[str, Any], ...]:
    """Return stable product rows with classifier paths and real providers."""
    load_all_sources()
    from server.modules.shared.price_services import cached_products

    products = tuple(cached_products())
    concrete = tuple(
        source for source in DataProviderProductTS.all()
        if not isinstance(source, DataProviderProductTSBundle)
    )
    bundles = tuple(
        source for source in DataProviderProductTS.all()
        if isinstance(source, DataProviderProductTSBundle)
    )
    rows: list[dict[str, Any]] = []
    for product in products:
        direct = tuple(source for source in concrete if _contains(source, product))
        bundle_ids = [
            str(bundle.key) for bundle in bundles
            if any(member in direct for member in bundle.members)
        ]
        name = str(
            getattr(product, "name", "") or getattr(product, "alias", "")
        )
        rows.append({
            "name": name,
            "desc": str(getattr(product, "desc", "") or name),
            "code": str(
                getattr(product, "code", "")
                or (name.split(".", 1)[0] if "." in name else name)
            ),
            "exchange": str(
                getattr(product, "exchange_id", "")
                or (name.split(".", 1)[1].split("@", 1)[0] if "." in name else "")
            ),
            "product_type": "product",
            "product_ref": f"product:{classifier_object_path(product)}",
            "product_path": classifier_object_path(product),
            "source_ids": sorted({*bundle_ids, *(str(source.key) for source in direct)}),
        })
    return tuple(sorted(rows, key=lambda row: (row["product_path"], row["name"])))


def clear_product_catalog_projection_cache() -> None:
    """Invalidate projections after a source registry or local cache refresh."""
    product_source_descriptors.cache_clear()
    catalog_product_records.cache_clear()
