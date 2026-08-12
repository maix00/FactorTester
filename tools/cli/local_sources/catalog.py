"""Read client-owned source manifests without importing provider code."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, unquote, urlsplit

from tools.cli.catalog import LocalCatalogStore

from .contracts import LocalSourceManifest, LocalSourceProduct, validate_local_source_manifest
from .locations import default_local_sources_root


_ROUTES = {
    "/api/client/product_sources",
    "/api/client/product_categories",
    "/api/client/product_names",
    "/api/client/product_fields",
    "/api/client/product_contracts",
    "/api/client/product_tree",
    "/api/client/contract_tree",
    "/api/client/product_prices",
    "/api/client/product-groups",
}


class ClientSourceCatalog:
    """Project local manifests into the embedded client's catalog contract."""

    def __init__(
        self,
        client_root: Path,
        source_root: Path | None = None,
    ) -> None:
        self.client_root = client_root.expanduser().resolve()
        self.source_root = (
            source_root or default_local_sources_root()
        ).expanduser().resolve()

    def request(
        self,
        path: str,
        *,
        method: str = "GET",
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        target = urlsplit(str(path or ""))
        group_detail = target.path.removeprefix("/api/client/product-groups/")
        is_group_detail = bool(group_detail) and target.path.startswith(
            "/api/client/product-groups/"
        )
        if (
            target.scheme or target.netloc
            or (target.path not in _ROUTES and not is_group_detail)
        ):
            raise ValueError("local catalog route is not allowed")
        verb = str(method or "GET").upper()
        if verb not in {"GET", "POST"}:
            raise ValueError("local catalog method is not allowed")
        query = parse_qs(target.query, keep_blank_values=True)
        selected = tuple(dict.fromkeys(
            value.strip()
            for value in query.get("data_source", [])
            if value.strip()
        ))
        manifests = self._selected_manifests(selected)
        if target.path == "/api/client/product_sources":
            return {"success": True, "origin": "local", "sources": [
                _source_descriptor(item) for item in manifests
            ]}
        if target.path == "/api/client/product_categories":
            return self._categories(manifests)
        if target.path == "/api/client/product_names":
            return self._products(manifests)
        if target.path == "/api/client/product_fields":
            return self._fields(manifests, _first(query, "name"))
        if target.path == "/api/client/product_tree":
            category_id = _first(query, "category")
            return {
                "success": True,
                "source": "local",
                "source_ids": [item.source_id for item in manifests],
                "category_id": category_id,
                "tree": _product_tree(manifests, category_id),
            }
        if target.path == "/api/client/contract_tree":
            return {
                "success": True,
                "source": "local",
                "nodes": _product_leaves(
                    manifests,
                    _first(query, "path"),
                    _first(query, "category"),
                ),
            }
        if target.path == "/api/client/product-groups" or is_group_detail:
            return self._groups(unquote(group_detail) or _first(query, "group_ref"))
        if target.path == "/api/client/product_contracts":
            return {
                "success": True,
                "source": "local",
                "product": _first(query, "product"),
                "contracts": [],
            }
        if target.path == "/api/client/product_prices":
            product = str((body or {}).get("product_name") or "")
            return {
                "success": True,
                "source": "local",
                "product": product,
                "data": [],
                "count": 0,
                "availability": "live_only",
            }
        raise AssertionError("unreachable local catalog route")

    def manifests(self) -> tuple[LocalSourceManifest, ...]:
        if not self.source_root.is_dir():
            return ()
        result: list[LocalSourceManifest] = []
        for path in sorted(self.source_root.glob("*/source.json")):
            if path.is_symlink() or not path.is_file():
                raise ValueError(
                    f"invalid local source manifest: {path.parent.name}"
                )
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                result.append(validate_local_source_manifest(value))
            except (OSError, ValueError, json.JSONDecodeError) as error:
                raise ValueError(
                    f"invalid local source manifest: {path.parent.name}"
                ) from error
        return tuple(result)

    def _selected_manifests(
        self,
        selected: Iterable[str],
    ) -> tuple[LocalSourceManifest, ...]:
        manifests = self.manifests()
        values = set(selected)
        if not values:
            return manifests
        known = {item.source_id for item in manifests}
        unknown = sorted(values - known)
        if unknown:
            raise ValueError(f"unknown local data source: {', '.join(unknown)}")
        return tuple(item for item in manifests if item.source_id in values)

    @staticmethod
    def _categories(
        manifests: tuple[LocalSourceManifest, ...],
    ) -> dict[str, Any]:
        unique: dict[str, dict[str, Any]] = {}
        for manifest in manifests:
            for category in manifest.categories:
                unique.setdefault(str(category["id"]), dict(category))
        return {
            "success": True,
            "source": "local",
            "default_category_id": None,
            "categories": list(unique.values()),
            "sources": [item.source_id for item in manifests],
        }

    @staticmethod
    def _products(
        manifests: tuple[LocalSourceManifest, ...],
    ) -> dict[str, Any]:
        return {
            "success": True,
            "source": "local",
            "source_ids": [item.source_id for item in manifests],
            "products": [
                _product_record(manifest, product)
                for manifest in manifests
                for product in manifest.products
            ],
        }

    @staticmethod
    def _fields(
        manifests: tuple[LocalSourceManifest, ...],
        name: str,
    ) -> dict[str, Any]:
        for manifest in manifests:
            for product in manifest.products:
                if name in {product.alias, product.product_ref}:
                    values = {
                        "product_ref": product.product_ref,
                        "display_name": product.display_name,
                        "product_kind": product.product_kind,
                        **product.metadata,
                    }
                    return {
                        "success": True,
                        "source": "local",
                        "name": product.alias,
                        "fields": [
                            {"name": key, "description": "", "value": value}
                            for key, value in values.items()
                        ],
                    }
        raise ValueError("local product does not exist")

    def _groups(self, group_ref: str) -> dict[str, Any]:
        store = LocalCatalogStore(self.client_root)
        store.initialize()
        groups = store.list_groups()
        result = []
        for group in groups:
            ref = str(group.get("group_ref") or "")
            value = dict(group)
            value["products"] = store.list_group_products(ref)
            value["source"] = "local"
            result.append(value)
        if group_ref:
            match = next(
                (item for item in result if item.get("group_ref") == group_ref),
                None,
            )
            if match is None:
                raise ValueError("local product group does not exist")
            return {"success": True, "source": "local", "group": match}
        return {"success": True, "source": "local", "groups": result}


def _source_descriptor(manifest: LocalSourceManifest) -> dict[str, Any]:
    available = set(manifest.availability["available_product_refs"])
    modes = [dict(member["data_mode"]) for member in manifest.members]
    return {
        "id": manifest.source_id,
        "source_ref": f"data-source:local:{manifest.source_id}",
        "source_name": manifest.source_name,
        "source_kind": "local",
        "provider_kind": manifest.provider_kind,
        "bundle_id": manifest.source_id,
        "bundle_name": manifest.source_name,
        "server_provided": False,
        "members": [
            {
                "id": member["id"],
                "label": member["label"],
                "frequency": member["data_mode"].get("frequency"),
                "timezone": member["timezone"],
                "time_columns": dict(member["time_columns"]),
                "data_columns": dict(member["data_columns"]),
                "product_count": len(available),
                "catalog_product_count": len(manifest.products),
            }
            for member in manifest.members
        ],
        "product_paths": sorted({item.class_path for item in manifest.products}),
        "categories": [dict(item) for item in manifest.categories],
        "data_modes": modes,
        "availability": {
            "status": manifest.availability["status"],
            "product_count": len(available),
            "frequency_names": sorted({
                str(mode["frequency"])
                for mode in modes if mode.get("frequency")
            }),
        },
        "catalog_product_count": len(manifest.products),
    }


def _product_record(
    manifest: LocalSourceManifest,
    product: LocalSourceProduct,
) -> dict[str, Any]:
    return {
        "name": product.alias,
        "code": str(product.metadata.get("code") or product.alias),
        "desc": product.display_name,
        "display_name": product.display_name,
        "product_ref": product.product_ref,
        "product_path": f"{product.class_path}/_products/{product.alias}",
        "product_kind": product.product_kind,
        "source_ids": [manifest.source_id],
        "metadata": dict(product.metadata),
    }


def _product_tree(
    manifests: tuple[LocalSourceManifest, ...],
    category_id: str = "",
) -> list[dict[str, Any]]:
    categories = _category_projection(manifests, category_id)
    root: dict[str, Any] = {"children": {}}
    for manifest in manifests:
        for product in manifest.products:
            projected_path = _projected_product_path(product, categories)
            if projected_path is None:
                continue
            current = root
            for part in projected_path:
                current = current["children"].setdefault(part, {"children": {}})
            current.setdefault("products", []).append((manifest, product))
    return [
        _tree_node(name, value, "")
        for name, value in sorted(root["children"].items())
    ]


def _tree_node(name: str, value: dict[str, Any], parent: str) -> dict[str, Any]:
    path = f"{parent}/{name}" if parent else name
    children = [
        _tree_node(child_name, child, path)
        for child_name, child in sorted(value.get("children", {}).items())
    ]
    products = value.get("products", [])
    product_leaves = [
        _product_leaf(manifest, product, path)
        for manifest, product in sorted(products, key=lambda item: item[1].alias)
    ]
    if product_leaves:
        children.insert(0, {
            "title": "Product Lists",
            "key": f"{path}/_products",
            "checkbox": False,
            "folder": True,
            "lazy": False,
            "children": product_leaves,
            "_product_count": len(product_leaves),
        })
    return {
        "title": name,
        "key": path,
        "checkbox": True,
        "folder": bool(children),
        "lazy": False,
        "children": children,
        "_product_count": sum(int(item.get("_product_count", 0)) for item in children),
    }


def _product_leaf(
    manifest: LocalSourceManifest,
    product: LocalSourceProduct,
    parent: str,
) -> dict[str, Any]:
    return {
        "title": product.alias,
        "key": f"{parent}/_products/{product.alias}",
        "checkbox": False,
        "folder": False,
        "lazy": False,
        "product_name": product.alias,
        "product_code": str(product.metadata.get("code") or product.alias),
        "product_ref": product.product_ref,
        "product_type": "product",
        "desc": product.display_name,
        "source_ids": [manifest.source_id],
        "_product_count": 1,
    }


def _product_leaves(
    manifests: tuple[LocalSourceManifest, ...],
    path: str,
    category_id: str = "",
) -> list[dict[str, Any]]:
    normalized = str(path or "").removesuffix("/_products")
    categories = _category_projection(manifests, category_id)
    return [
        _product_leaf(manifest, product, normalized)
        for manifest in manifests
        for product in manifest.products
        if _path_text(_projected_product_path(product, categories)) == normalized
    ]


def _category_projection(
    manifests: tuple[LocalSourceManifest, ...],
    category_id: str,
) -> tuple[dict[str, Any], ...]:
    requested = str(category_id or "").strip()
    if not requested:
        return ()
    definitions: dict[str, dict[str, Any]] = {}
    base_order: list[str] = []
    for manifest in manifests:
        for category in manifest.categories:
            category_ref = str(category["id"])
            definitions.setdefault(category_ref, dict(category))
            if category["composable"] and not category["is_composite"]:
                for dimension in category["dimensions"]:
                    dimension_ref = str(dimension)
                    if dimension_ref not in base_order:
                        base_order.append(dimension_ref)
    dimensions = _category_dimensions(requested, definitions, tuple(base_order))
    return tuple(_base_category(definitions, dimension) for dimension in dimensions)


def _category_dimensions(
    category_id: str,
    definitions: dict[str, dict[str, Any]],
    base_order: tuple[str, ...],
) -> tuple[str, ...]:
    exact = definitions.get(category_id)
    if exact is not None:
        requested = tuple(str(value) for value in exact["dimensions"])
    else:
        parsed = _split_category_id(category_id, base_order)
        if parsed is None:
            raise ValueError(f"unknown local product Category: {category_id}")
        requested = parsed
    requested_set = set(requested)
    if len(requested_set) != len(requested):
        raise ValueError("local product Category repeats a dimension")
    canonical = tuple(value for value in base_order if value in requested_set)
    if set(canonical) != requested_set:
        raise ValueError("local product Category contains an unknown dimension")
    return canonical


def _split_category_id(
    value: str,
    base_order: tuple[str, ...],
) -> tuple[str, ...] | None:
    if value in base_order:
        return (value,)
    for dimension in sorted(base_order, key=len, reverse=True):
        prefix = f"{dimension}_x_"
        if value.startswith(prefix):
            rest = _split_category_id(value[len(prefix):], base_order)
            if rest is not None:
                return (dimension, *rest)
    return None


def _base_category(
    definitions: dict[str, dict[str, Any]],
    dimension: str,
) -> dict[str, Any]:
    match = next((
        definition
        for definition in definitions.values()
        if definition["composable"]
        and not definition["is_composite"]
        and tuple(definition["dimensions"]) == (dimension,)
    ), None)
    if match is None:
        raise ValueError(f"local product Category dimension is unavailable: {dimension}")
    return match


def _projected_product_path(
    product: LocalSourceProduct,
    categories: tuple[dict[str, Any], ...],
) -> tuple[str, ...] | None:
    classifier = tuple(Path(product.class_path).parts)
    if not categories:
        return classifier
    values: list[str] = []
    for category in categories:
        dimension = str(category["dimensions"][0])
        value_path = product.category_values.get(dimension)
        if not value_path:
            return None
        values.append(" › ".join(value_path))
    titles = [
        str(category.get("title_zh") or category.get("alias") or category["id"])
        for category in categories
    ]
    if len(categories) == 1:
        dimension = str(categories[0]["dimensions"][0])
        return (*classifier, titles[0], *product.category_values[dimension])
    return (*classifier, "×".join(titles), f"({'×'.join(values)})")


def _path_text(path: tuple[str, ...] | None) -> str:
    return "/".join(path or ())


def _first(query: dict[str, list[str]], key: str) -> str:
    return str(query.get(key, [""])[0] or "").strip()
