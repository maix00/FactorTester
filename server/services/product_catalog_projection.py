"""Source-owned projections for the Manager product catalog.

The Manager catalog is independent from any backtest service port.  Concrete
source modules declare their catalog scope and capabilities; this module only
projects those declarations for Web and embedded clients.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Iterable, Mapping

from sources.registry import load_all_sources
from tools.data.source_catalog import (
    DataSourceDeclaration,
    DataSourceMember,
    data_source_declarations,
)
from tools.products.classifier_paths import (
    classifier_class_path,
    classifier_object_path,
)


def _supports(source: Any, product: Any) -> bool:
    try:
        return bool(source.supports_product(product))
    except Exception:
        return False


def _contains(source: Any, product: Any) -> bool:
    try:
        return bool(source.has_available_data(product))
    except Exception:
        return False


def _available_products(
    source: Any, products: Iterable[Any],
) -> tuple[Any, ...]:
    return tuple(product for product in products if _contains(source, product))


def _supported_products(
    source: Any, products: Iterable[Any],
) -> tuple[Any, ...]:
    return tuple(product for product in products if _supports(source, product))


@lru_cache(maxsize=2)
def _visible_source_index(origin: str = "server") -> dict[str, DataSourceDeclaration]:
    load_all_sources()
    return {
        source.key: source
        for source in data_source_declarations(_normalize_origin(origin))
    }


def normalize_source_ids(
    source_ids: Iterable[str] | None,
    origin: str = "server",
) -> tuple[str, ...]:
    """Validate and normalize source IDs visible at one catalog origin."""
    if source_ids is None:
        return ()
    values = tuple(dict.fromkeys(
        str(value or "").strip()
        for value in source_ids
        if str(value or "").strip()
    ))
    unknown = sorted(set(values) - set(_visible_source_index(origin)))
    if unknown:
        raise ValueError(f"未知产品数据源: {', '.join(unknown)}")
    return values


def available_source_ids(origin: str = "server") -> tuple[str, ...]:
    """Return visible sources with currently available product data."""
    return tuple(
        descriptor["id"]
        for descriptor in product_source_descriptors(origin)
        if int(descriptor.get("availability", {}).get("product_count", 0)) > 0
    )


def catalog_source_ids(origin: str = "server") -> tuple[str, ...]:
    """Return sources declaring at least one supported catalog product."""
    return tuple(
        descriptor["id"]
        for descriptor in product_source_descriptors(origin)
        if int(descriptor.get("catalog_product_count", 0)) > 0
    )


def filter_product_records(
    source_ids: Iterable[str] | None,
    origin: str = "server",
) -> tuple[dict[str, Any], ...]:
    """Filter searchable products by source-owned catalog declarations."""
    selected = set(normalize_source_ids(source_ids, origin))
    rows = catalog_product_records(origin)
    if not selected:
        return rows
    return tuple(
        row for row in rows
        if selected.intersection(row.get("source_ids", ()))
    )


def filter_product_tree(
    tree: Mapping[Any, Any],
    source_ids: Iterable[str] | None,
    origin: str = "server",
) -> dict[Any, Any]:
    """Return a source-filtered tree without mutating the CategoryTree."""
    selected_ids = normalize_source_ids(source_ids, origin)
    visible = _visible_source_index(origin)
    sources = (
        tuple(visible[source_id] for source_id in selected_ids)
        if selected_ids else tuple(visible.values())
    )
    if not sources:
        return {}

    def filtered(value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        result: dict[Any, Any] = {}
        for key, child in value.items():
            if key == "$OBJECTS$":
                objects = [
                    product for product in child
                    if any(_supports(source, product) for source in sources)
                ]
                if objects:
                    result[key] = objects
                continue
            if isinstance(child, Mapping):
                next_child = filtered(child)
                if _tree_has_products(next_child):
                    result[key] = next_child
            else:
                result[key] = child
        return result

    return filtered(tree)


def _tree_has_products(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    if value.get("$OBJECTS$"):
        return True
    return any(
        _tree_has_products(child)
        for key, child in value.items()
        if key != "$OBJECTS$"
    )


def _member_descriptor(
    member: DataSourceMember,
    products: tuple[Any, ...],
) -> dict[str, Any]:
    return {
        "id": member.key,
        "label": member.label,
        "frequency": member.frequency,
        "timezone": member.timezone,
        "time_columns": dict(member.time_columns),
        "data_columns": dict(member.data_columns),
        "product_count": len(_available_products(member, products)),
        "catalog_product_count": len(_supported_products(member, products)),
    }


@lru_cache(maxsize=2)
def product_source_descriptors(
    origin: str = "server",
) -> tuple[dict[str, Any], ...]:
    """Return source-owned declarations visible at one catalog origin."""
    load_all_sources()
    from server.modules.shared.price_services import (
        available_product_categories,
        cached_products,
    )

    source_origin = _normalize_origin(origin)
    products = tuple(cached_products())
    categories = available_product_categories()
    result: list[dict[str, Any]] = []
    for source in _visible_source_index(source_origin).values():
        members = tuple(
            _member_descriptor(member, products)
            for member in source.members
        )
        available = _available_products(source, products)
        supported = _supported_products(source, products)
        frequencies = sorted({
            member["frequency"] for member in members if member["frequency"]
        })
        result.append({
            "id": source.key,
            "source_ref": f"data-source:{source_origin}:{source.key}",
            "source_name": source.label,
            "source_kind": source_origin,
            "provider_kind": source.provider_kind,
            "bundle_id": source.key,
            "bundle_name": source.label,
            "server_provided": source_origin == "server",
            "members": list(members),
            "product_paths": sorted({
                classifier_class_path(type(product)) for product in supported
            }),
            "categories": categories,
            "data_modes": [mode.as_dict() for mode in source.modes()],
            "availability": {
                "status": "ready" if available else source.empty_status,
                "product_count": len(available),
                "frequency_names": frequencies,
            },
            "catalog_product_count": len(supported),
        })
    return tuple(result)


@lru_cache(maxsize=2)
def catalog_product_records(
    origin: str = "server",
) -> tuple[dict[str, Any], ...]:
    """Return stable product rows and their visible source declarations."""
    load_all_sources()
    from server.modules.shared.price_services import cached_products

    sources = tuple(_visible_source_index(origin).values())
    rows: list[dict[str, Any]] = []
    for product in tuple(cached_products()):
        supported = tuple(source for source in sources if _supports(source, product))
        if not supported:
            continue
        available = tuple(source for source in sources if _contains(source, product))
        name = str(getattr(product, "name", "") or getattr(product, "alias", ""))
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
            "source_ids": sorted(source.key for source in supported),
            "available_source_ids": sorted(source.key for source in available),
        })
    return tuple(sorted(rows, key=lambda row: (row["product_path"], row["name"])))


def clear_product_catalog_projection_cache() -> None:
    """Invalidate projections after a source registry or cache refresh."""
    product_source_descriptors.cache_clear()
    catalog_product_records.cache_clear()
    _visible_source_index.cache_clear()


def _normalize_origin(origin: str) -> str:
    return "local" if str(origin).strip().lower() == "local" else "server"
