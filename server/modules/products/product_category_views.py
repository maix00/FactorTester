"""Render the classifier product tree with optional category projections.

The product tree is always built from the Python classifier classes and the
products registered by data sources.  A selected product category is only a
parallel view attached below the concrete class that owns its products; it is
never rendered as a top-level or replacement tree.

Product-category definitions themselves are resolved by
``product_category_paths``.  This module deliberately does not construct a
category-owned product tree.  That distinction is important for both the
product page and the label editor: the latter requests this renderer without
category selections and therefore receives only the ordinary classifier
tree.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from server.services.product_tree import convert_to_fancytree

_CATEGORY_MARKER = "ProductCategory"


def normalize_category_selection(values: str | Iterable[str] | None) -> list[str]:
    """Normalize repeated and comma-separated category query values."""
    if values is None:
        return []
    raw_values = [values] if isinstance(values, str) else values
    result: list[str] = []
    for raw in raw_values:
        for value in str(raw or "").split(","):
            category_id = value.strip()
            if category_id and category_id not in result:
                result.append(category_id)
    return result


def render_product_tree(
    category_ids: str | Iterable[str] | None = None,
    *,
    principal: str = "",
    source_ids: Iterable[str] | None = None,
    checkbox_default: bool = False,
) -> list[dict[str, Any]]:
    """Render the ordinary classifier tree plus selected category views.

    The root and every normal branch come from ``cached_product_tree``.  A
    category view is added under each concrete classifier class with direct
    products.  Multiple selected categories remain siblings, so selecting two
    categories never creates a Cartesian-product tree.
    """
    selected = normalize_category_selection(category_ids)
    tree = _base_product_tree(source_ids)
    nodes = convert_to_fancytree(tree, checkbox_default=checkbox_default)
    if selected:
        memberships = _category_memberships(selected, principal)
        _append_category_views(
            nodes, tree, memberships, checkbox_default=checkbox_default,
        )
    return nodes


def tree_for_path(
    path: str | None,
    category_ids: str | Iterable[str] | None = None,
    *,
    principal: str = "",
    source_ids: Iterable[str] | None = None,
) -> tuple[Mapping[Any, Any], str]:
    """Return the ordinary internal tree and a classifier lookup path.

    A lazy category label path is normalized to its owning Python class path.
    The concrete category members are obtained separately by
    :func:`category_products_for_path`; no synthetic category tree is built.
    """
    selected = normalize_category_selection(category_ids)
    value = str(path or "").strip().strip("/")
    parsed = _split_category_view_path(value)
    tree = _base_product_tree(source_ids)
    if parsed is None:
        return tree, value

    class_path, category_id, _label = parsed
    _validate_category_view(class_path, category_id, selected, tree)
    return tree, class_path


def category_products_for_path(
    path: str | None,
    category_ids: str | Iterable[str] | None = None,
    *,
    principal: str = "",
    source_ids: Iterable[str] | None = None,
) -> list[Any] | None:
    """Resolve one displayed category-label node to concrete products.

    ``None`` means that ``path`` is an ordinary classifier path.  An empty
    list is a valid category selection with no products after source filtering.
    """
    value = str(path or "").strip().strip("/")
    parsed = _split_category_view_path(value)
    if parsed is None:
        return None
    class_path, category_id, label = parsed
    selected = normalize_category_selection(category_ids)
    tree = _base_product_tree(source_ids)
    _validate_category_view(class_path, category_id, selected, tree)
    class_node = _find_internal_path(tree, class_path)
    direct_products = tuple(class_node.get("$OBJECTS$") or [])
    direct_paths = _product_paths(direct_products)
    members = _category_memberships([category_id], principal)[category_id][1]
    return [
        product for product in members.get(label, ())
        if _product_path(product) in direct_paths
    ]


def _base_product_tree(source_ids: Iterable[str] | None) -> Mapping[Any, Any]:
    from server.modules.shared.price_services import cached_product_tree
    from server.services.product_catalog_projection import filter_product_tree

    tree = cached_product_tree().tree
    return filter_product_tree(tree, source_ids) if source_ids is not None else tree


def _category_memberships(
    category_ids: Iterable[str], principal: str,
) -> dict[str, tuple[str, dict[str, tuple[Any, ...]]]]:
    from server.modules.products.product_category_paths import _category_members
    from server.modules.products.product_category_store import get_product_category
    from server.modules.shared.price_services import available_product_categories

    result: dict[str, tuple[str, dict[str, tuple[Any, ...]]]] = {}
    available = {
        str(item.get("id") or ""): item
        for item in available_product_categories()
    }
    for category_id in category_ids:
        definition = get_product_category(principal, category_id) if principal else None
        definition = definition or available.get(category_id)
        if definition is None and "×" in category_id:
            parts = category_id.split("×")
            if all(part in available for part in parts):
                definition = {
                    "id": category_id,
                    "title_zh": "×".join(
                        str(available[part].get("title_zh")
                            or available[part].get("alias") or part)
                        for part in parts
                    ),
                }
        if definition is None:
            raise ValueError(f"产品分类不存在: {category_id}")
        title = str(
            definition.get("title_zh")
            or definition.get("alias")
            or category_id
        )
        result[category_id] = (title, {
            str(label): tuple(products)
            for label, products in _category_members(category_id, principal).items()
        })
    return result


def _append_category_views(
    nodes: list[dict[str, Any]],
    tree: Mapping[Any, Any],
    memberships: Mapping[str, tuple[str, Mapping[str, Iterable[Any]]]],
    *,
    checkbox_default: bool,
) -> None:
    """Attach category labels below their owning classifier class nodes."""
    for node in nodes:
        path = str(node.get("key") or "").strip("/")
        value = _find_internal_path(tree, path)
        if isinstance(value, Mapping):
            direct_products = tuple(value.get("$OBJECTS$") or ())
            if direct_products:
                _append_category_children(
                    node, path, direct_products, memberships,
                    checkbox_default=checkbox_default,
                )
        _append_category_views(
            node.get("children") or [], tree, memberships,
            checkbox_default=checkbox_default,
        )


def _append_category_children(
    node: dict[str, Any],
    class_path: str,
    direct_products: tuple[Any, ...],
    memberships: Mapping[str, tuple[str, Mapping[str, Iterable[Any]]]],
    *,
    checkbox_default: bool,
) -> None:
    direct_paths = _product_paths(direct_products)
    category_nodes: list[dict[str, Any]] = []
    for category_id, (title, labels) in memberships.items():
        label_nodes: list[dict[str, Any]] = []
        category_prefix = f"{class_path}/{_CATEGORY_MARKER}/{category_id}"
        for label, products in labels.items():
            selected = tuple(
                product for product in products
                if _product_path(product) in direct_paths
            )
            if not selected:
                continue
            label_nodes.append({
                "title": label,
                "key": f"{category_prefix}/{label}",
                "folder": True,
                "lazy": True,
                "checkbox": checkbox_default,
                "desc": f"{len(selected)} 个产品",
            })
        if label_nodes:
            category_nodes.append({
                "title": title,
                "key": category_prefix,
                "folder": True,
                "lazy": False,
                "checkbox": False,
                "expanded": True,
                "children": sorted(
                    label_nodes, key=lambda item: str(item["title"]),
                ),
            })
    if not category_nodes:
        return
    children = node.setdefault("children", [])
    if not children:
        node["folder"] = True
        node["lazy"] = False
        children.append({
            "title": "Product Lists",
            "key": f"{class_path}/_products",
            "folder": True,
            "lazy": True,
            "checkbox": False,
        })
    children.extend(category_nodes)


def _split_category_view_path(
    path: str,
) -> tuple[str, str, str] | None:
    parts = [item for item in str(path or "").strip("/").split("/") if item]
    try:
        marker_index = parts.index(_CATEGORY_MARKER)
    except ValueError:
        return None
    if marker_index < 1:
        return None
    if len(parts) <= marker_index + 2:
        raise ValueError("产品分类节点路径格式无效")
    class_path = "/".join(parts[:marker_index])
    category_id = parts[marker_index + 1]
    label = "/".join(parts[marker_index + 2:])
    if not class_path or not category_id or not label:
        raise ValueError("产品分类节点路径格式无效")
    return class_path, category_id, label


def _validate_category_view(
    class_path: str,
    category_id: str,
    selected: Iterable[str],
    tree: Mapping[Any, Any],
) -> None:
    if category_id not in selected:
        raise ValueError("产品分类节点与当前选择不匹配")
    if not isinstance(_find_internal_path(tree, class_path), Mapping):
        raise ValueError("产品分类节点所属的产品 class 不存在")


def _find_internal_path(tree: Mapping[Any, Any], path: str) -> Any:
    """Resolve a classifier class path in the base tree mapping."""
    parts = [item for item in str(path or "").strip("/").split("/") if item]
    current: Any = tree
    for part in parts:
        if not isinstance(current, Mapping):
            return None
        entries: list[tuple[Any, Any]] = []
        for key, value in current.items():
            if key not in {"$SUBCLASS$", "$OBJECTS$"}:
                entries.append((key, value))
        subclasses = current.get("$SUBCLASS$")
        if isinstance(subclasses, Mapping):
            entries.extend(subclasses.items())
        match = next(
            (
                value for key, value in entries
                if (str(key) if not isinstance(key, type) else key.__name__)
                == part
            ),
            None,
        )
        if match is None:
            return None
        current = match
    return current


def _product_path(product: Any) -> str:
    from tools.products.classifier_paths import classifier_object_path

    return classifier_object_path(product)


def _product_paths(products: Iterable[Any]) -> set[str]:
    return {_product_path(product) for product in products}
