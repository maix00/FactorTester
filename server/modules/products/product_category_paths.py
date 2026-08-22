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


_CATEGORY_PATH_PREFIX = "ProductCategory"


def canonicalize_product_paths(
    raw_paths: Iterable[str] | None,
    *,
    category_ids: Iterable[str] | None = None,
    username: str = "",
    allow_unresolved: bool = False,
    infer_legacy_categories: bool = True,
) -> list[str]:
    """Return minimal signed paths in the category-free classifier namespace."""
    requested_categories = _normalize_category_ids(category_ids, username)
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
        view = _category_view_components(path)
        if view is not None:
            class_path, view_category_ref, view_label_ref = view
            view_category_id, view_label = _resolve_category_label_reference(
                view_category_ref, view_label_ref, username,
            )
            if not _is_stable_category_id(view_category_id, username):
                raise ValueError(
                    "带分类的产品路径必须使用已登记的产品分类 ID: "
                    + view_category_id
                )
            if requested_categories and view_category_id not in requested_categories:
                raise ValueError(
                    f"产品路径引用的分类 {view_category_id} 未绑定到当前定义"
                )
            members = _category_members(view_category_id, username)
            prefix = class_path.rstrip("/") + "/"
            canonical = [
                product_path
                for product in members.get(view_label, [])
                if (
                    (product_path := classifier_object_path(product)) == class_path
                    or product_path.startswith(prefix)
                )
            ]
            if not canonical:
                raise ValueError(f"无法解析产品分类 Label: {view_label}")
            (negative if negative_path else positive).extend(canonical)
            continue
        qualified_ref, path = _split_category_qualified_path(path)
        qualified_id = (
            _resolve_category_reference(qualified_ref, username)
            if qualified_ref else ""
        )
        candidate_trees = category_trees
        if qualified_id:
            if not _is_stable_category_id(qualified_id, username):
                raise ValueError(
                    "带分类的产品路径必须使用已登记的产品分类 ID: "
                    + qualified_id
                )
            if requested_categories and qualified_id not in requested_categories:
                raise ValueError(
                    f"产品路径引用的分类 {qualified_id} 未绑定到当前定义"
                )
            if not requested_categories:
                candidate_trees = [
                    (qualified_id, _category_tree(qualified_id, username)),
                ]
            else:
                candidate_trees = [
                    (category_id, tree)
                    for category_id, tree in category_trees
                    if category_id == qualified_id
                ]
        canonical = _canonical_path_candidates(path, candidate_trees)
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


def normalize_category_selection_paths(
    raw_paths: Iterable[str] | None,
    *,
    username: str = "",
) -> list[str]:
    """Normalize category-mounted selections to stable ID-based references.

    This editor representation is kept beside the legacy concrete ``paths``
    column. Ordinary classifier paths are unchanged; a mounted category view
    is rewritten from category/label titles to
    ``ProductCategory/<category_id>/<label_id>`` while preserving its owning
    classifier prefix and sign.
    """
    result: list[str] = []
    for raw in raw_paths or []:
        if not isinstance(raw, str) or not raw.strip():
            continue
        signed = raw.strip()
        negative = signed.startswith("-")
        path = signed[1:].strip() if negative else signed
        parsed = _category_view_components(path)
        if parsed is not None:
            class_path, category_ref, label_ref = parsed
            category_id, label_id, _label = _resolve_category_label_identity(
                category_ref, label_ref, username,
            )
            normalized = (
                f"{class_path}/{_CATEGORY_PATH_PREFIX}/"
                f"{category_id}/{label_id}"
            )
        else:
            qualified_ref, relative = _split_category_qualified_path(path)
            if qualified_ref:
                normalized = (
                    f"{_CATEGORY_PATH_PREFIX}/"
                    f"{_resolve_category_reference(qualified_ref, username)}/"
                    f"{relative}"
                )
            else:
                normalized = path.strip("/")
        result.append(f"-{normalized}" if negative else normalized)
    return list(dict.fromkeys(result))


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
        view_category_ref, view_label_ref = _split_category_view_path(path)
        if view_category_ref:
            view_category_id, _view_label = _resolve_category_label_reference(
                view_category_ref, view_label_ref, username,
            )
            if _is_stable_category_id(view_category_id, username):
                if view_category_id not in result:
                    result.append(view_category_id)
            continue
        explicit_ref, path = _split_category_qualified_path(path)
        explicit_id = (
            _resolve_category_reference(explicit_ref, username)
            if explicit_ref else ""
        )
        if explicit_id:
            if _is_stable_category_id(explicit_id, username):
                result.append(explicit_id) if explicit_id not in result else None
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
    # A user-owned composite is a normal stored category.  Its parent IDs are
    # provenance only; the label/path snapshot created at registration is the
    # authoritative tree and must not drift when a parent is later edited.
    if (
        definition is not None
        and definition.get("is_composite")
    ):
        return _custom_category_tree(definition, cached_product_tree().tree)

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
    } or wanted == _source_composite_category_id()


def _normalize_category_ids(
    category_ids: Iterable[str] | None,
    username: str,
) -> list[str]:
    """Normalize source aliases while preserving user-category IDs exactly."""
    from server.modules.shared.price_services import normalize_product_category_id

    result: list[str] = []
    for raw in category_ids or []:
        value = str(raw or "").strip()
        if not value:
            continue
        if username:
            from server.modules.products.product_category_store import (
                get_product_category,
            )

            if get_product_category(username, value) is not None:
                if value not in result:
                    result.append(value)
                continue
        try:
            normalized = normalize_product_category_id(value)
        except ValueError:
            normalized = value
        if normalized not in result:
            result.append(normalized)
    return result


def _split_category_qualified_path(path: str) -> tuple[str, str]:
    """Extract the stable category ID from a selectable tree path.

    The web tree prefixes explicit category selections as
    ``ProductCategory/<category_id>/<classifier-path>``.  The prefix is the
    only category identity used for resolution; display titles that occur in
    the classifier path remain implementation data and are never parsed as an
    ID.
    """
    value = str(path or "").strip().strip("/")
    parts = value.split("/") if value else []
    if len(parts) < 3 or parts[0] != _CATEGORY_PATH_PREFIX:
        return "", value
    category_id = parts[1].strip()
    relative = "/".join(parts[2:]).strip("/")
    if not category_id or not relative:
        raise ValueError("带分类的产品路径格式无效")
    return category_id, relative


def _resolve_category_reference(value: str, username: str) -> str:
    """Resolve either a stable category ID or an exact category title.

    IDs are the only persisted identity.  Titles are accepted at the input
    boundary for CLI/editor ergonomics and are rejected when ambiguous.
    """
    reference = str(value or "").strip()
    if not reference:
        raise ValueError("产品分类引用不能为空")
    if _is_stable_category_id(reference, username):
        return reference
    from server.modules.products.product_category_store import (
        list_product_categories,
    )

    matches = [
        item for item in list_product_categories(username)
        if reference in {
            str(item.get("title_zh") or "").strip(),
            str(item.get("alias") or "").strip(),
        }
    ]
    if not matches:
        raise ValueError(
            f"产品分类不存在: {reference}；带分类的产品路径必须使用已登记的产品分类 ID: {reference}"
        )
    if len(matches) > 1:
        raise ValueError(f"产品分类标题不唯一，请使用 ID: {reference}")
    return str(matches[0].get("id") or "").strip()


def _resolve_category_label_reference(
    category_ref: str,
    label_ref: str,
    username: str,
) -> tuple[str, str]:
    """Resolve category/label IDs or titles to the canonical pair."""
    category_id, _label_id, label = _resolve_category_label_identity(
        category_ref, label_ref, username,
    )
    return category_id, label


def _resolve_category_label_identity(
    category_ref: str,
    label_ref: str,
    username: str,
) -> tuple[str, str, str]:
    """Resolve category and label references and return both stable IDs."""
    category_id = _resolve_category_reference(category_ref, username)
    label_reference = str(label_ref or "").strip()
    if not label_reference:
        raise ValueError("产品分类 Label 引用不能为空")
    from server.modules.products.product_category_store import (
        get_product_category,
        list_product_categories,
    )

    category = get_product_category(username, category_id)
    if category is None:
        category = next(
            (
                item for item in list_product_categories(username)
                if str(item.get("id") or "") == category_id
            ),
            None,
        )
    if category is None:
        raise ValueError(f"产品分类不存在: {category_id}")
    items = category.get("items") or []
    matches = [
        item for item in items
        if label_reference in {
            str(item.get("label_id") or "").strip(),
            str(item.get("label") or item.get("title") or "").strip(),
        }
    ]
    if not matches:
        raise ValueError(
            f"产品分类 Label 不存在: {category_id}/{label_reference}",
        )
    if len(matches) > 1:
        raise ValueError(
            f"产品分类 Label 标题不唯一，请使用 Label ID: {label_reference}",
        )
    label = str(
        matches[0].get("label") or matches[0].get("title") or "",
    ).strip()
    return category_id, str(matches[0].get("label_id") or "").strip(), label


def _split_category_view_path(path: str) -> tuple[str, str]:
    """Extract a category label from a classifier-owned view path.

    The product page renders a selected category below its owning Python
    classifier class, for example::

        Product/Futures/CNFutures/ProductCategory/cnfutures_sector/行业

    This is a selection path for a product group, not a persisted product
    path.  It is expanded to concrete classifier paths before persistence.
    """
    parsed = _category_view_components(path)
    if parsed is None:
        return "", ""
    _class_path, category_ref, label_ref = parsed
    return category_ref, label_ref


def _category_view_components(
    path: str,
) -> tuple[str, str, str] | None:
    """Return classifier path plus category and label references."""
    parts = [item for item in str(path or "").strip("/").split("/") if item]
    try:
        marker_index = parts.index(_CATEGORY_PATH_PREFIX)
    except ValueError:
        return None
    if marker_index < 1:
        return None
    if len(parts) <= marker_index + 2:
        raise ValueError("产品分类节点路径格式无效")
    class_path = "/".join(parts[:marker_index]).strip("/")
    category_ref = parts[marker_index + 1].strip()
    label_ref = "/".join(parts[marker_index + 2:]).strip()
    if not class_path or not category_ref or not label_ref:
        raise ValueError("产品分类节点路径格式无效")
    return class_path, category_ref, label_ref


def _is_stable_category_id(category_id: str, username: str = "") -> bool:
    """Return whether a path prefix names a registered stable category ID."""
    wanted = str(category_id or "").strip()
    if not wanted:
        return False
    if wanted in _known_source_category_ids():
        return True
    if username:
        from server.modules.products.product_category_store import (
            get_product_category,
        )

        return get_product_category(username, wanted) is not None
    return False


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


def compose_category_items(
    parent_ids: list[str] | tuple[str, ...],
    username: str,
) -> list[dict[str, Any]]:
    """Create a one-time label/path snapshot for a pair of categories."""
    if len(parent_ids) != 2 or len(set(parent_ids)) != 2:
        raise ValueError("产品乘积分类必须绑定两个不同的父分类")
    left = _category_members(str(parent_ids[0]), username)
    right = _category_members(str(parent_ids[1]), username)
    result: list[dict[str, Any]] = []
    for left_label, left_objects in left.items():
        if left_label == "Others":
            continue
        left_index = {
            classifier_object_path(item): item for item in left_objects
        }
        for right_label, right_objects in right.items():
            if right_label == "Others":
                continue
            right_index = {
                classifier_object_path(item): item for item in right_objects
            }
            paths = sorted(left_index.keys() & right_index.keys())
            if paths:
                result.append({
                    "label": f"({left_label}×{right_label})",
                    "paths": paths,
                })
    # Category always owns an ``Others`` complement.  Persist the resolved
    # paths as a generated row so a later edit can display the exact snapshot
    # without allowing a client to rename or rewrite it.
    from server.modules.shared.price_services import cached_product_tree

    covered = {
        path
        for item in result
        for path in item.get("paths") or []
    }
    others = sorted({
        classifier_object_path(product)
        for product in _collect_products(cached_product_tree().tree)
        if classifier_object_path(product) not in covered
    })
    if others:
        result.append({
            "label": "Others",
            "paths": others,
            "label_generated": True,
        })
    return result


def regenerate_generated_others(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Rebuild an existing generated ``Others`` row from explicit members.

    The client never supplies the complement as authoritative data.  On a
    save, explicit rows are resolved against the current local product tree;
    the complement is then written back with the reserved label and its
    existing row position when possible.  Categories without an existing
    generated row are left unchanged, so this helper cannot be used to add a
    client-declared ``Others`` label.
    """
    generated_positions = [
        index for index, item in enumerate(items)
        if str(item.get("label") or "").strip() == "Others"
        or bool(item.get("label_generated"))
    ]
    if not generated_positions:
        return items
    explicit = [
        dict(item) for item in items
        if str(item.get("label") or "").strip() != "Others"
        and not bool(item.get("label_generated"))
    ]
    from server.modules.shared.price_services import cached_product_tree

    covered: set[str] = set()
    base_tree = cached_product_tree().tree
    for item in explicit:
        included: set[str] = set()
        excluded: set[str] = set()
        for raw_path in item.get("paths") or []:
            signed = str(raw_path or "").strip()
            negative = signed.startswith("-")
            path = signed[1:].strip() if negative else signed
            for product in _node_products(path, base_tree):
                key = classifier_object_path(product)
                (excluded if negative else included).add(key)
        covered.update(included - excluded)
    all_paths = {
        classifier_object_path(product)
        for product in _collect_products(base_tree)
    }
    others = sorted(all_paths - covered)
    if not others:
        return explicit
    generated = {
        "label": "Others",
        "paths": others,
        "label_generated": True,
    }
    insert_at = min(generated_positions[0], len(explicit))
    return [*explicit[:insert_at], generated, *explicit[insert_at:]]


def _source_category_members(category_id: str) -> dict[str, list[Any]]:
    """Extract source-category labels from its provider-owned tree."""
    from server.modules.shared.price_services import (
        CN_FUTURES_COMPOSITE_CATEGORY_ID,
        CN_FUTURES_DAY_NIGHT_CATEGORY_ID,
        CN_FUTURES_SECTOR_CATEGORY_ID,
    )

    aliases = {
        CN_FUTURES_DAY_NIGHT_CATEGORY_ID: "日夜盘",
        CN_FUTURES_SECTOR_CATEGORY_ID: "行业",
        CN_FUTURES_COMPOSITE_CATEGORY_ID: "日夜盘×行业",
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
    if len(ids) == 2:
        return (*ids, _source_composite_category_id())
    return ids


def _source_composite_category_id() -> str:
    from server.modules.shared.price_services import (
        CN_FUTURES_COMPOSITE_CATEGORY_ID,
    )

    return CN_FUTURES_COMPOSITE_CATEGORY_ID
