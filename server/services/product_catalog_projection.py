"""Source-owned projections for the Manager product catalog.

The Manager catalog is independent from any backtest service port.  Concrete
source modules declare their catalog scope and capabilities; this module only
projects those declarations for Web and embedded clients.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Iterable, Mapping

from sources.registry import installed_bundles, load_all_sources
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


def catalog_product_description(product: Any, name: str = "") -> str:
    """Return a human-facing product description without alias fallback.

    ``name`` and ``code`` are stable machine identifiers, not descriptions.
    Source adapters may expose a localized label through either a direct
    attribute or metadata; a term-structure contract may inherit its parent
    product label.  If no source-owned label exists, return an empty string so
    the UI can show its placeholder instead of displaying the code twice.
    """
    machine_names = {
        str(value or "").strip()
        for value in (
            name,
            getattr(product, "name", ""),
            getattr(product, "alias", ""),
            getattr(product, "code", ""),
        )
        if str(value or "").strip()
    }
    metadata = getattr(product, "metadata", {})
    metadata_values = (
        metadata.get(key)
        for key in (
            "display_name_zh", "description_zh", "underlying_name_zh",
            "display_name", "description", "desc",
        )
    ) if isinstance(metadata, Mapping) else ()
    values = (*metadata_values, *(getattr(product, key, "") for key in (
        "display_name", "description_zh", "desc",
    )))
    for value in values:
        text = str(value or "").strip()
        if text and text not in machine_names:
            return text

    try:
        from tools.products.product_utils import product_display_name

        inherited = str(product_display_name(product).get("desc") or "").strip()
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        inherited = ""
    return inherited if inherited and inherited not in machine_names else ""


def _available_products(
    source: Any, products: Iterable[Any],
) -> tuple[Any, ...]:
    return tuple(product for product in products if _contains(source, product))


def _supported_products(
    source: Any, products: Iterable[Any],
) -> tuple[Any, ...]:
    return tuple(product for product in products if _supports(source, product))


@lru_cache(maxsize=1)
def _visible_source_index() -> dict[str, DataSourceDeclaration]:
    load_all_sources()
    return {
        source.key: source
        for source in data_source_declarations()
    }


def installed_bundle_descriptors(
    *, execution_location: str | None = None,
) -> tuple[dict[str, Any], ...]:
    """Return installed Bundle metadata without activating source plugins.

    Availability and product counts are deliberately unknown here: they require
    live source/product probes and belong to the runtime projection, not a
    metadata-only catalog read.
    """
    if execution_location not in {None, "server", "client"}:
        raise ValueError("execution_location must be server, client, or None")
    rows: list[dict[str, Any]] = []
    for bundle in installed_bundles():
        if execution_location is not None and bundle.execution_location != execution_location:
            continue
        members = tuple({
            "id": member.id,
            "kind": member.kind,
            "data_type": member.data_type,
            "frequency": member.frequency,
            "related_members": list(member.related_members),
            "integrations": dict(member.integrations),
            "update_policy": {
                "mode": member.update_policy.mode,
                "revision_policy": member.update_policy.revision_policy,
                "max_staleness_seconds": member.update_policy.max_staleness_seconds,
                "replay_policy": member.update_policy.replay_policy,
            },
        } for member in bundle.members)
        rows.append({
            "id": bundle.bundle_id,
            "bundle_id": bundle.bundle_id,
            "version": bundle.version,
            "label": bundle.label,
            "provisioner": bundle.provisioner,
            "execution_location": bundle.execution_location,
            "members": list(members),
            "frequencies": sorted({
                member["frequency"] for member in members if member["frequency"]
            }),
            "product_bindings": [
                {
                    "product_ref": binding.product_ref,
                    "source_product_ref": binding.source_product_ref,
                    "member_id": binding.member_id,
                }
                for binding in bundle.product_bindings
            ],
            "availability": {"status": "unknown", "product_count": None},
        })
    return tuple(rows)


def normalize_source_ids(
    source_ids: Iterable[str] | None,
) -> tuple[str, ...]:
    """Validate and normalize source IDs registered by this server."""
    if source_ids is None:
        return ()
    values = tuple(dict.fromkeys(
        str(value or "").strip()
        for value in source_ids
        if str(value or "").strip()
    ))
    unknown = sorted(set(values) - set(_visible_source_index()))
    if unknown:
        raise ValueError(f"未知产品数据源: {', '.join(unknown)}")
    return values


def available_source_ids() -> tuple[str, ...]:
    """Return visible sources with currently available product data."""
    return tuple(
        descriptor["id"]
        for descriptor in product_source_descriptors()
        if int(descriptor.get("availability", {}).get("product_count", 0)) > 0
    )


def catalog_source_ids() -> tuple[str, ...]:
    """Return sources declaring at least one supported catalog product."""
    return tuple(
        descriptor["id"]
        for descriptor in product_source_descriptors()
        if int(descriptor.get("catalog_product_count", 0)) > 0
    )


def filter_product_records(
    source_ids: Iterable[str] | None,
) -> tuple[dict[str, Any], ...]:
    """Filter searchable products by source-owned catalog declarations."""
    selected = set(normalize_source_ids(source_ids))
    rows = catalog_product_records()
    if not selected:
        return rows
    return tuple(
        row for row in rows
        if selected.intersection(row.get("source_ids", ()))
    )


def filter_product_tree(
    tree: Mapping[Any, Any],
    source_ids: Iterable[str] | None,
) -> dict[Any, Any]:
    """Return a source-filtered tree without mutating the CategoryTree."""
    selected_ids = normalize_source_ids(source_ids)
    visible = _visible_source_index()
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
    nautilus_capability: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    available = _available_products(member, products)
    supported = _supported_products(member, products)
    mode = member.mode.as_dict()
    return {
        "id": member.key,
        "source_ref": f"data-source-member:server:{member.key}",
        "label": member.label,
        "frequency": member.frequency,
        "timezone": member.timezone,
        "time_columns": dict(member.time_columns),
        "data_columns": dict(member.data_columns),
        "dimensions": dict(member.dimensions),
        "data_modes": [mode],
        "naming_scheme": member.naming_scheme,
        # Preserve the source server's verified NT adapter admission in the
        # federated catalog snapshot. The UI can still show accurate details
        # when this member is supplied by another server.
        "nautilus_capability": dict(nautilus_capability or {}),
        "product_paths": sorted({
            classifier_class_path(type(product)) for product in supported
        }),
        "availability": {
            "status": "ready" if available else "empty",
            "product_count": len(available),
            "frequency_names": [member.frequency] if member.frequency else [],
        },
        "product_count": len(available),
        "catalog_product_count": len(supported),
    }


@lru_cache(maxsize=1)
def product_source_descriptors() -> tuple[dict[str, Any], ...]:
    """Return source-owned declarations registered by this server."""
    load_all_sources()
    from server.modules.shared.price_services import (
        available_product_categories,
        cached_contracts,
        cached_products,
    )

    products = tuple(cached_products())
    # A source member can be product-level or contract-level.  Keep the
    # family-level statistics product-based for compatibility, but calculate
    # every member from the complete catalog so contract feeds do not appear
    # empty merely because they are not ordinary Product objects.
    catalog_objects = (*products, *tuple(cached_contracts()))
    categories = available_product_categories()
    try:
        from server.services.nautilus_bridge.capabilities import (
            market_data_source_capabilities,
        )

        nautilus_member_capabilities = {
            str(item.get("member_key") or ""): item
            for item in market_data_source_capabilities().get("members", [])
            if isinstance(item, Mapping) and str(item.get("member_key") or "")
        }
    except Exception:
        # Source metadata remains available if the execution bridge is absent;
        # its adapter status is then unknown rather than inferred.
        nautilus_member_capabilities = {}
    result: list[dict[str, Any]] = []
    for source in _visible_source_index().values():
        members = tuple(
            _member_descriptor(
                member, catalog_objects,
                _catalog_nautilus_capability(
                    nautilus_member_capabilities.get(member.key),
                ),
            )
            for member in source.members
        )
        naming_schemes = sorted({
            str(member.get("naming_scheme") or "").strip()
            for member in members
            if str(member.get("naming_scheme") or "").strip()
        })
        member_product_paths = {
            str(path).strip()
            for member in members
            for path in member.get("product_paths") or ()
            if str(path).strip()
        }
        available = _available_products(source, products)
        supported = _supported_products(source, products)
        frequencies = sorted({
            member["frequency"] for member in members if member["frequency"]
        })
        result.append({
            "id": source.key,
            "family_id": source.key,
            "family_name": source.label,
            "source_ref": f"data-source:server:{source.key}",
            "source_name": source.label,
            "source_kind": "server",
            "provider_kind": source.provider_kind,
            "bundle_id": source.key,
            "bundle_name": source.label,
            "server_provided": True,
            "members": list(members),
            "naming_schemes": naming_schemes,
            # A source family can expose several concrete member classes.  A
            # family page must advertise their union, including contract-only
            # paths that are absent from the ordinary product collection.
            "product_paths": sorted(member_product_paths | {
                classifier_class_path(type(product))
                for product in supported
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


def _catalog_nautilus_capability(
    capability: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Keep federated source metadata compact; full mappings stay in detail API."""
    if not isinstance(capability, Mapping) or not capability:
        return {}
    keys = (
        "adapter_available", "adapter_id", "supported_book_types", "reason",
        "instrument_scope", "bar_time_semantics", "raw_timestamp_unit", "layout",
    )
    return {key: capability[key] for key in keys if key in capability}


@lru_cache(maxsize=1)
def catalog_product_records() -> tuple[dict[str, Any], ...]:
    """Return stable product rows and their server source declarations."""
    load_all_sources()
    from server.modules.shared.price_services import cached_products

    sources = tuple(_visible_source_index().values())
    rows: list[dict[str, Any]] = []
    for product in tuple(cached_products()):
        supported = tuple(source for source in sources if _supports(source, product))
        if not supported:
            continue
        available = tuple(source for source in sources if _contains(source, product))
        name = str(getattr(product, "name", "") or getattr(product, "alias", ""))
        description = catalog_product_description(product, name)
        rows.append({
            "name": name,
            "desc": description,
            "description": description,
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


def source_ids_for_product_paths(
    paths: Iterable[str] | None,
    source_descriptors: Iterable[Mapping[str, Any]] | None = None,
) -> tuple[str, ...]:
    """Infer source bundles from declared classifier path namespaces.

    ``Product/Futures/CNFutures`` is already the correct persisted path.  This
    helper only compares it with each source descriptor's declared
    ``product_paths``; it never expands the node into individual products.
    Passing ``source_descriptors`` lets an embedded client use the same
    resolver for user-owned manifests.  When omitted, the server registry is
    used.
    """
    return tuple(sorted({
        source_id
        for source_ids in source_ids_by_product_path(
            paths, source_descriptors,
        ).values()
        for source_id in source_ids
    }))


def source_ids_by_product_path(
    paths: Iterable[str] | None,
    source_descriptors: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, tuple[str, ...]]:
    """Resolve many persisted paths with one normalized source index."""
    originals = tuple(dict.fromkeys(
        str(value or "").strip()
        for value in paths or ()
        if str(value or "").strip()
    ))
    if not originals:
        return {}
    descriptors = tuple(
        source_descriptors
        if source_descriptors is not None else product_source_descriptors()
    )
    declared_by_source: list[tuple[str, tuple[str, ...]]] = []
    for descriptor in descriptors:
        source_id = str(
            descriptor.get("id") or descriptor.get("source_id") or ""
        ).strip()
        declared_values = []
        for value in descriptor.get("product_paths") or ():
            normalized = _category_free_path(value)
            if normalized and normalized not in declared_values:
                declared_values.append(normalized)
        declared_paths = tuple(declared_values)
        if source_id and declared_paths:
            declared_by_source.append((source_id, declared_paths))
    result: dict[str, tuple[str, ...]] = {}
    for original in originals:
        requested = _category_free_path(original)
        result[original] = tuple(sorted(
            source_id
            for source_id, declared_paths in declared_by_source
            if requested and any(
                _paths_overlap(requested, declared)
                for declared in declared_paths
            )
        ))
    return result


def source_family_ids_for_member_ids(
    member_ids: Iterable[str] | None,
    source_descriptors: Iterable[Mapping[str, Any]] | None = None,
) -> tuple[str, ...]:
    """Resolve concrete data-source members to their source-family IDs.

    Product rows are allowed to report the concrete provider that actually
    serves a product, while the catalog UI links only to the owning source
    family.  Unknown IDs are retained so an embedded or federated descriptor
    can still display a useful value instead of silently dropping a source.
    """
    requested = tuple(dict.fromkeys(
        str(value or "").strip()
        for value in member_ids or ()
        if str(value or "").strip()
    ))
    if not requested:
        return ()
    descriptors = tuple(
        source_descriptors
        if source_descriptors is not None else product_source_descriptors()
    )
    member_to_family: dict[str, str] = {}
    for descriptor in descriptors:
        family_id = str(
            descriptor.get("family_id")
            or descriptor.get("bundle_id")
            or descriptor.get("id")
            or ""
        ).strip()
        if not family_id:
            continue
        for member in descriptor.get("members") or ():
            if not isinstance(member, Mapping):
                continue
            member_id = str(member.get("id") or "").strip()
            if member_id:
                member_to_family[member_id] = family_id
    return tuple(sorted({member_to_family.get(value, value) for value in requested}))


def _category_free_path(value: object) -> str:
    path = str(value or "").strip().lstrip("-").strip().strip("/")
    parts = path.split("/") if path else []
    if len(parts) >= 3 and parts[0] == "ProductCategory":
        return "/".join(parts[2:]).strip("/")
    return path


def _paths_overlap(requested: str, declared: str) -> bool:
    """Return whether a requested node is provided by a declared source node.

    Matching is intentionally directional.  A source declaring
    ``Product/Futures/CNFutures`` provides that node and its descendants, but
    it does not provide the hard-coded backend parent ``Product/Futures``.
    """
    return requested == declared or requested.startswith(declared + "/")


def clear_product_catalog_projection_cache() -> None:
    """Invalidate projections after a source registry or cache refresh."""
    product_source_descriptors.cache_clear()
    catalog_product_records.cache_clear()
    _visible_source_index.cache_clear()
