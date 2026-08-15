"""Canonicalize category-qualified product paths.

Product groups persist only classifier paths.  A category-qualified selection
is resolved once against its explicit category tree and expanded to the exact
category-free object paths; no category is inferred at runtime for a new
group.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache
from typing import Any

from server.services.product_tree import find_node_by_path, get_minimal_paths
from tools.products.classifier_paths import classifier_object_path


def canonicalize_product_paths(
    raw_paths: Iterable[str] | None,
    *,
    category_ids: Iterable[str] | None = None,
    username: str = "",
    allow_unresolved: bool = False,
    infer_legacy_categories: bool = True,
) -> list[str]:
    """Return minimal signed paths in the category-free classifier namespace."""
    requested_categories = list(dict.fromkeys(
        str(value or "").strip() for value in category_ids or []
        if str(value or "").strip()
    ))
    category_trees = [
        (category_id, _category_tree(category_id, username))
        for category_id in requested_categories
    ]
    # Legacy rows may contain a category-qualified path but no saved binding.
    # Infer only while migrating an existing row; callers creating new groups
    # pass an explicit category and reject unresolved category paths.
    if not requested_categories and infer_legacy_categories:
        category_trees = [
            (category_id, _category_tree(category_id, username))
            for category_id in _known_source_category_ids()
        ]

    positive: list[str] = []
    negative: list[str] = []
    for raw in raw_paths or []:
        if not isinstance(raw, str) or not raw.strip():
            continue
        signed = raw.strip()
        negative_path = signed.startswith("-")
        path = signed[1:].strip() if negative_path else signed
        canonical = _canonical_path_candidates(path, category_trees)
        if not canonical:
            if allow_unresolved and _matches_known_category_path(
                path, username=username, category_ids=requested_categories,
            ):
                raise ValueError(f"无法解析产品路径，请绑定对应分类: {path}")
            if not allow_unresolved:
                raise ValueError(f"无法解析产品路径，请绑定对应分类: {path}")
            canonical = [path]
        (negative if negative_path else positive).extend(canonical)

    return get_minimal_paths(_unique(positive)) + [
        f"-{path}" for path in get_minimal_paths(_unique(negative))
    ]


def infer_category_ids(
    raw_paths: Iterable[str] | None,
    *,
    username: str = "",
) -> list[str]:
    """Return source category IDs that explain at least one qualified path."""
    result: list[str] = []
    categories = [
        (category_id, _category_tree(category_id, username))
        for category_id in _known_source_category_ids()
    ]
    for raw in raw_paths or []:
        path = str(raw or "").strip().lstrip("-").strip()
        if not path:
            continue
        for category_id, tree in categories:
            if _node_products(path, tree):
                if category_id not in result:
                    result.append(category_id)
                break
    return result


def category_tree(category_id: str, username: str = "") -> Any:
    """Expose one source or account-owned category tree to catalog services."""
    return _category_tree(category_id, username)


@lru_cache(maxsize=16)
def _source_category_tree(category_id: str) -> Any:
    from server.modules.shared.price_services import cached_product_tree_for_category

    return cached_product_tree_for_category(category_id).tree


def _category_tree(category_id: str, username: str) -> Any:
    from server.modules.shared.price_services import (
        cached_product_tree,
        normalize_product_category_id,
    )

    from server.modules.products.product_category_store import get_product_category

    definition = get_product_category(username, category_id) if username else None
    # A user-owned composite must remain resolvable after it is persisted.  A
    # source composite (day_night_x_sector) is handled by the provider's
    # stable implementation below; custom composites need to combine their
    # two parent trees here instead of relying on browser-local definitions.
    if (
        definition is not None
        and definition.get("is_composite")
        and not _is_source_category_id(category_id)
    ):
        parents = [
            str(value).strip()
            for value in definition.get("parent_category_ids") or []
            if str(value).strip()
        ]
        if len(parents) != 2:
            raise ValueError(f"产品乘积分类缺少父分类: {category_id}")
        return _composite_category_tree(parents, username, definition)

    try:
        normalized = normalize_product_category_id(category_id)
    except ValueError:
        normalized = ""
    if normalized:
        return _source_category_tree(normalized)

    if definition is None:
        raise ValueError(f"产品分类不存在: {category_id}")
    return _custom_category_tree(definition, cached_product_tree().tree)


def _is_source_category_id(category_id: object) -> bool:
    """Return whether an id is one of the provider's stable category ids."""
    from server.modules.shared.price_services import available_product_categories

    wanted = str(category_id or "").strip()
    return wanted in {
        str(item.get("id") or "") for item in available_product_categories()
    } or wanted == "day_night_x_sector"


def _custom_category_tree(definition: dict[str, Any], base_tree: Any) -> dict[Any, Any]:
    from tools.products.Product import Product

    root: dict[Any, Any] = {Product: {}}
    category_node = root[Product].setdefault(
        str(definition.get("title_zh") or definition.get("alias") or definition["id"]),
        {},
    )
    for item in definition.get("items") or []:
        included: dict[str, Any] = {}
        excluded: set[str] = set()
        for raw_path in item.get("paths") or []:
            signed = str(raw_path or "").strip()
            negative = signed.startswith("-")
            path = signed[1:].strip() if negative else signed
            for product in _node_products(path, base_tree):
                key = classifier_object_path(product)
                if negative:
                    excluded.add(key)
                else:
                    included.setdefault(key, product)
        unique = [product for key, product in included.items() if key not in excluded]
        if unique:
            category_node[str(item.get("label") or "")] = {"$OBJECTS$": unique}
    return root


def _composite_category_tree(
    parent_ids: list[str],
    username: str,
    definition: dict[str, Any],
) -> dict[Any, Any]:
    """Build a declarative Cartesian product for a user-owned composite."""
    if len(parent_ids) != 2:
        raise ValueError("产品乘积分类必须有两个父分类")
    left = _category_members(parent_ids[0], username)
    right = _category_members(parent_ids[1], username)
    from tools.products.Product import Product

    root: dict[Any, Any] = {Product: {}}
    category_node = root[Product].setdefault(
        str(definition.get("title_zh") or definition.get("alias") or definition["id"]),
        {},
    )
    for left_label, left_objects in left.items():
        left_index = {
            classifier_object_path(item): item for item in left_objects
        }
        for right_label, right_objects in right.items():
            right_index = {
                classifier_object_path(item): item for item in right_objects
            }
            common = [
                left_index[key] for key in left_index.keys() & right_index.keys()
            ]
            if common:
                category_node[f"({left_label}×{right_label})"] = {
                    "$OBJECTS$": common,
                }
    return root


def _category_members(category_id: str, username: str) -> dict[str, list[Any]]:
    """Return one category's labels and concrete objects for composition."""
    from server.modules.shared.price_services import normalize_product_category_id

    try:
        normalized = normalize_product_category_id(category_id)
    except ValueError:
        normalized = ""
    if normalized:
        return _source_category_members(normalized)

    from server.modules.products.product_category_store import get_product_category
    from server.modules.shared.price_services import cached_product_tree

    definition = get_product_category(username, category_id) if username else None
    if definition is None:
        raise ValueError(f"产品分类不存在: {category_id}")
    if definition.get("is_composite"):
        parents = [
            str(value).strip()
            for value in definition.get("parent_category_ids") or []
            if str(value).strip()
        ]
        if len(parents) != 2:
            raise ValueError(f"产品乘积分类缺少父分类: {category_id}")
        left = _category_members(parents[0], username)
        right = _category_members(parents[1], username)
        result: dict[str, list[Any]] = {}
        for left_label, left_objects in left.items():
            left_index = {
                classifier_object_path(item): item for item in left_objects
            }
            for right_label, right_objects in right.items():
                right_index = {
                    classifier_object_path(item): item for item in right_objects
                }
                common = [
                    left_index[key]
                    for key in left_index.keys() & right_index.keys()
                ]
                if common:
                    result[f"({left_label}×{right_label})"] = common
        return result

    result = {}
    base_tree = cached_product_tree().tree
    for item in definition.get("items") or []:
        included: dict[str, Any] = {}
        excluded: set[str] = set()
        for raw_path in item.get("paths") or []:
            signed = str(raw_path or "").strip()
            negative = signed.startswith("-")
            path = signed[1:].strip() if negative else signed
            for product in _node_products(path, base_tree):
                key = classifier_object_path(product)
                if negative:
                    excluded.add(key)
                else:
                    included.setdefault(key, product)
        members = [
            product for key, product in included.items() if key not in excluded
        ]
        if members:
            result[str(item.get("label") or "")] = members
    return result


def _source_category_members(category_id: str) -> dict[str, list[Any]]:
    """Extract source-category labels from its provider-owned tree."""
    aliases = {
        "day_night": "日夜盘",
        "sector": "行业",
        "day_night_x_sector": "日夜盘×行业",
    }
    title = aliases.get(category_id, category_id)
    tree = _source_category_tree(category_id)
    result: dict[str, list[Any]] = {}

    def walk(value: Any) -> None:
        if not isinstance(value, dict):
            return
        for key, child in value.items():
            if key == "$OBJECTS$":
                continue
            if key == "$SUBCLASS$":
                walk(child)
                continue
            label = key.__name__ if isinstance(key, type) else str(key)
            if label == title and isinstance(child, dict):
                for child_key, child_value in child.items():
                    if child_key in {"$OBJECTS$", "$SUBCLASS$"}:
                        continue
                    child_label = (
                        child_key.__name__ if isinstance(child_key, type)
                        else str(child_key)
                    )
                    products = _collect_products(child_value)
                    if products:
                        result.setdefault(child_label, []).extend(products)
            if isinstance(child, dict):
                walk(child)

    walk(tree)
    return {
        label: _unique_objects(objects)
        for label, objects in result.items()
        if objects
    }


def _unique_objects(values: Iterable[Any]) -> list[Any]:
    result = []
    seen: set[str] = set()
    for value in values:
        key = classifier_object_path(value)
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _matches_known_category_path(
    path: str,
    *,
    username: str,
    category_ids: Iterable[str],
) -> bool:
    """Recognize a category-qualified path before preserving unknown paths."""
    candidates = list(dict.fromkeys(
        str(value).strip() for value in category_ids if str(value).strip()
    ))
    if not candidates:
        candidates = list(_known_source_category_ids())
        if username:
            from server.modules.products.product_category_store import (
                list_product_categories,
            )

            candidates.extend(
                str(item.get("id") or "")
                for item in list_product_categories(username)
                if str(item.get("id") or "")
            )
    for category_id in dict.fromkeys(candidates):
        try:
            if _node_products(path, _category_tree(category_id, username)):
                return True
        except (LookupError, TypeError, ValueError):
            continue
    return False


def _canonical_path_candidates(path: str, category_trees: list[tuple[str, Any]]) -> list[str]:
    from server.modules.shared.price_services import cached_product_tree

    if _node_exists(path, cached_product_tree().tree):
        return [path]
    for _category_id, tree in category_trees:
        products = _node_products(path, tree)
        if products:
            return _unique([classifier_object_path(product) for product in products])
    return []


def _node_exists(path: str, tree: Any) -> bool:
    return find_node_by_path(tree, path.split("/")) is not None


def _node_products(path: str, tree: Any) -> list[Any]:
    node = find_node_by_path(tree, path.split("/"))
    return _collect_products(node)


def _collect_products(node: Any) -> list[Any]:
    if node is None:
        return []
    if not isinstance(node, dict):
        return [node]
    result: list[Any] = []
    objects = node.get("$OBJECTS$")
    if isinstance(objects, list):
        result.extend(objects)
    for key, value in node.items():
        if key == "$OBJECTS$":
            continue
        if isinstance(value, dict):
            result.extend(_collect_products(value))
    return result


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value).strip()))


def _known_source_category_ids() -> tuple[str, ...]:
    from server.modules.shared.price_services import available_product_categories

    ids = tuple(str(item["id"]) for item in available_product_categories())
    if {"day_night", "sector"}.issubset(ids):
        return (*ids, "day_night_x_sector")
    return ids
