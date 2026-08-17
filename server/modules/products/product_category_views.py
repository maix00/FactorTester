"""Render one or more product-category projections as a parallel forest."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from server.services.product_tree import convert_to_fancytree

_PARALLEL_CATEGORY_PREFIX = "ProductCategory"


def normalize_category_selection(values: str | Iterable[str] | None) -> list[str]:
    """Normalize repeated/comma-separated category query values.

    ``×`` remains reserved for a registered composite category ID.  It is
    deliberately not a separator here: two selected categories are rendered
    as separate sibling trees, while a registered composite is one category.
    """
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
    """Render selected categories as sibling roots, never as a union.

    Every explicit category receives a stable ``ProductCategory/<id>``
    wrapper.  This makes paths emitted by the selectable tree carry the fixed
    category ID even when only one category is selected; multiple categories
    remain parallel sibling trees rather than a Cartesian product.
    """
    selected = normalize_category_selection(category_ids)
    if not selected:
        return _render_one("", principal, source_ids, checkbox_default)
    if len(selected) == 1:
        category_id = selected[0] if selected else ""
        return [_parallel_root(
            category_id,
            _render_one(category_id, principal, source_ids, checkbox_default),
            principal,
        )]
    return [
        _parallel_root(
            category_id,
            _render_one(category_id, principal, source_ids, checkbox_default),
            principal,
        )
        for category_id in selected
    ]


def tree_for_path(
    path: str | None,
    category_ids: str | Iterable[str] | None = None,
    *,
    principal: str = "",
    source_ids: Iterable[str] | None = None,
) -> tuple[Mapping[Any, Any], str]:
    """Return the internal tree and path for a lazy product-list request."""
    selected = normalize_category_selection(category_ids)
    category_id, relative_path = _parallel_path(path)
    if category_id:
        if category_id not in selected:
            raise ValueError("产品分类节点与当前选择不匹配")
        return _internal_tree(category_id, principal, source_ids), relative_path
    if len(selected) > 1:
        raise ValueError("并列产品分类节点缺少分类前缀")
    category = selected[0] if selected else ""
    return _internal_tree(category, principal, source_ids), relative_path


def _render_one(
    category_id: str,
    principal: str,
    source_ids: Iterable[str] | None,
    checkbox_default: bool,
) -> list[dict[str, Any]]:
    return convert_to_fancytree(
        _internal_tree(category_id, principal, source_ids),
        checkbox_default=checkbox_default,
    )


def _internal_tree(
    category_id: str,
    principal: str,
    source_ids: Iterable[str] | None,
) -> Mapping[Any, Any]:
    from server.modules.products.product_category_paths import category_tree
    from server.modules.shared.price_services import cached_product_tree
    from server.services.product_catalog_projection import filter_product_tree

    tree = category_tree(category_id, principal) if category_id else cached_product_tree().tree
    return filter_product_tree(tree, source_ids) if source_ids is not None else tree


def _parallel_root(
    category_id: str,
    nodes: list[dict[str, Any]],
    principal: str,
) -> dict[str, Any]:
    from server.modules.products.product_category_store import get_product_category
    from server.modules.shared.price_services import available_product_categories

    definition = get_product_category(principal, category_id) if principal else None
    if definition is None:
        definition = next(
            (
                item for item in available_product_categories()
                if str(item.get("id") or "") == category_id
            ),
            None,
        )
    title = str(
        (definition or {}).get("title_zh")
        or (definition or {}).get("alias")
        or category_id
    )
    if definition is None and "×" in category_id:
        source_titles = {
            str(item.get("id") or ""): str(
                item.get("title_zh") or item.get("alias") or item.get("id")
            )
            for item in available_product_categories()
        }
        title = "×".join(source_titles.get(part, part)
                          for part in category_id.split("×"))
    prefix = f"{_PARALLEL_CATEGORY_PREFIX}/{category_id}"
    children = []
    for node in nodes:
        if node.get("title") == "Product" and node.get("children"):
            children.extend(_prefix_node(child, prefix) for child in node["children"])
        else:
            children.append(_prefix_node(node, prefix))
    return {
        "title": title,
        "key": prefix,
        "folder": True,
        "lazy": False,
        "checkbox": False,
        "expanded": True,
        "children": children,
    }


def _prefix_node(node: dict[str, Any], prefix: str) -> dict[str, Any]:
    value = dict(node)
    key = str(value.get("key") or "").lstrip("/")
    value["key"] = f"{prefix}/{key}" if key else prefix
    if isinstance(value.get("children"), list):
        value["children"] = [
            _prefix_node(child, prefix) for child in value["children"]
        ]
    return value


def _parallel_path(path: str | None) -> tuple[str, str]:
    value = str(path or "").strip().strip("/")
    parts = value.split("/") if value else []
    if len(parts) >= 3 and parts[0] == _PARALLEL_CATEGORY_PREFIX:
        return parts[1], "/".join(parts[2:])
    return "", value
