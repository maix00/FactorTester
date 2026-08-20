"""Account-owned product category definitions and catalog projections."""

from __future__ import annotations

import time
from typing import Any

from tools.data.account_manage import (
    load_product_categories,
    save_product_categories,
)
from tools.data.sqlite.account_manager.domain_sync import enqueue_entity

from server.modules.products.product_category_definition import (
    canonical_category_reference as _canonical_category_reference,
    category_id as _category_id,
    category_name as _category_name,
    category_view as _category_view,
    composite_category_id as _composite_category_id,
    load_source_category_overrides as _load_source_category_overrides,
    migrate_owned_category_id,
    migrate_owned_category_path,
    migrate_legacy_category_id,
    migrate_legacy_category_path,
    migrate_owned_definition as _migrate_owned_definition,
    new_user_category_id as _new_user_category_id,
    normalize_definition as _normalize_definition,
    normalize_composite_label_updates as _normalize_composite_label_updates,
    normalize_items as _normalize_items,
    validate_category_items as _validate_category_items,
    validate_generated_items_unchanged as _validate_generated_items_unchanged,
    save_source_category_override as _save_source_category_override,
    shared_source_ids as _shared_source_ids,
    source_category_definitions as _source_category_definitions,
    source_category_items as _source_category_items,
)


class ProductCategoryInUseError(ValueError):
    """Raised when a category is still bound to one or more product groups."""

    status = 409

    def __init__(self, category_id: str, references: list[dict[str, Any]]):
        self.category_id = str(category_id or "").strip()
        self.references = [dict(item) for item in references]
        labels = [
            str(item.get("name") or item.get("id") or "").strip()
            for item in self.references
        ]
        detail = "、".join(item for item in labels if item)
        suffix = f"：{detail}" if detail else ""
        super().__init__(f"产品分类仍被产品组引用，不能删除{suffix}")


def product_group_references(
    username: str,
    category_id: str,
) -> list[dict[str, Any]]:
    """Return product groups that explicitly bind ``category_id``.

    The import stays local because product groups validate their category IDs
    through this module.  Keeping the dependency at call time avoids a module
    cycle while making deletion checks use the same migrated SQLite view as
    the product-group editor.
    """
    from server.modules.products.product_group_store import load_product_groups

    wanted = str(category_id or "").strip()
    if not wanted:
        return []
    result: list[dict[str, Any]] = []
    for group in load_product_groups(username):
        category_ids = {
            str(value or "").strip()
            for value in group.get("category_ids") or []
            if str(value or "").strip()
        }
        if wanted not in category_ids:
            continue
        result.append({
            "id": str(group.get("id") or "").strip(),
            "name": str(group.get("name") or "").strip(),
        })
    return sorted(
        result,
        key=lambda item: (
            str(item.get("name") or "").casefold(),
            str(item.get("id") or ""),
        ),
    )


def list_product_categories(username: str) -> list[dict[str, Any]]:
    """Return source categories followed by categories owned by ``username``."""
    from server.modules.shared.price_services import available_product_categories

    overrides = _load_source_category_overrides()
    source = []
    for item in available_product_categories():
        value = dict(item)
        override = overrides.get(str(value.get("id") or ""))
        if override:
            value.update({
                key: override[key]
                for key in ("alias", "title_zh")
                if override.get(key)
            })
        value["items"] = _source_category_items(value["id"])
        projected = _category_view(
            value, kind="source", owner_ref="source", source_managed=True,
        )
        projected["path_sources"] = _category_path_sources(projected.get("items") or [])
        source.append(projected)
    owned = []
    raw_owned = load_product_categories(username)
    migrated_owned = []
    for item in raw_owned:
        migrated = _migrate_owned_definition(item, username)
        value = _normalize_definition(migrated)
        if not value.get("is_composite"):
            inferred = infer_category_source_ids(value.get("items") or [])
            if value.get("source_ids") != inferred:
                value["source_ids"] = inferred
        migrated_owned.append(dict(value))
        projected = _category_view(
            value, kind="user", owner_ref=f"user:{username}",
            source_managed=False,
        )
        projected["path_sources"] = _category_path_sources(projected.get("items") or [])
        owned.append(projected)
    if migrated_owned != raw_owned:
        save_product_categories(username, migrated_owned)
    return source + owned


def _category_path_sources(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from server.services.product_catalog_projection import source_ids_by_product_path

    paths = list(dict.fromkeys(
        str(path or "").removeprefix("-").strip()
        for item in items
        for path in item.get("paths") or []
        if str(path or "").removeprefix("-").strip()
    ))
    source_ids = source_ids_by_product_path(paths)
    return [
        {"path": path, "source_ids": list(source_ids.get(path, ()))}
        for path in paths
    ]


def get_product_category(
    username: str,
    category_id: str,
) -> dict[str, Any] | None:
    wanted = str(category_id or "").strip()
    return next(
        (item for item in list_product_categories(username)
         if str(item.get("id") or "") == wanted),
        None,
    )


def create_product_category(
    username: str,
    name: str,
    items: list[dict[str, Any]],
    category_id: str | None = None,
) -> dict[str, Any]:
    title = _category_name(name)
    normalized_items = _validate_category_items(_normalize_items(items))
    if any(item.get("label") == "Others" for item in normalized_items):
        raise ValueError("Others 标签由系统自动生成，不能由客户端新增")
    from server.modules.products.product_category_paths import canonicalize_product_paths

    normalized_items = [
        {
            **item,
            "paths": canonicalize_product_paths(
                item["paths"], username=username,
            ),
        }
        for item in normalized_items
    ]
    source_ids = infer_category_source_ids(normalized_items)
    categories = load_product_categories(username)
    if any(
        str(item.get("title_zh") or item.get("alias") or "").strip() == title
        for item in list_product_categories(username)
    ):
        raise ValueError("产品分类名称已存在")
    if category_id not in (None, ""):
        raise ValueError("产品分类 ID 由服务器生成，不能由客户端指定")
    requested_id = _new_user_category_id(username)
    category = _normalize_definition({
        "id": requested_id,
        "alias": title,
        "title_zh": title,
        "dimensions": [],
        "source_ids": source_ids,
        "composable": True,
        "is_composite": False,
        "kind": "user",
        "items": normalized_items,
        "created_at": time.time(),
        "updated_at": time.time(),
    })
    categories.append(category)
    save_product_categories(username, categories)
    return list_product_categories(username)[-1]


def create_product_category_composition(
    username: str,
    category_ids: list[str],
) -> dict[str, Any]:
    if not isinstance(category_ids, list):
        raise ValueError("category_ids 必须是字符串数组")
    available = list_product_categories(username)
    known_ids = {str(item.get("id") or "") for item in available}
    selected = list(dict.fromkeys(
        str(value).strip() if str(value).strip() in known_ids
        else _canonical_category_reference(value)
        for value in category_ids
        if str(value or "").strip()
    ))
    if len(selected) != 2:
        raise ValueError("请选择两个不同的分类")
    definitions = {
        str(item.get("id") or ""): item
        for item in available
    }
    parents = [definitions.get(value) for value in selected]
    if any(item is None for item in parents):
        raise ValueError("所选分类已不存在")
    if any(not item.get("composable", True) for item in parents if item):
        raise ValueError("所选分类不能参与乘积")

    # The two parent IDs are the identity of a composition.  This keeps the
    # object shared with ordinary categories and makes reversed selections
    # resolve to the same row instead of creating a duplicate random ID.
    selected = sorted(selected)
    parents = [definitions.get(value) for value in selected]
    composite_id = _composite_category_id(selected)
    if any(str(item.get("id") or "") == composite_id for item in load_product_categories(username)):
        raise ValueError("该乘积分类已存在")
    labels = [
        str(item.get("title_zh") or item.get("alias") or item.get("id"))
        for item in parents
    ]
    dimensions = []
    for item in parents:
        dimensions.extend(item.get("dimensions") or [item.get("id")])
    source_ids = _shared_source_ids(parents)
    from server.modules.products.product_category_paths import compose_category_items

    category = _normalize_definition({
        "id": composite_id,
        "alias": "×".join(labels),
        "title_zh": "×".join(labels),
        "dimensions": list(dict.fromkeys(dimensions)),
        "source_ids": source_ids,
        "composable": True,
        "is_composite": True,
        "parent_category_ids": selected,
        # Store the resolved intersection now.  Parent IDs below are
        # provenance and are used only when the explicit refresh action is
        # requested later.
        "items": compose_category_items(selected, username),
        "created_at": time.time(),
        "updated_at": time.time(),
    })
    categories = load_product_categories(username)
    categories.append(category)
    save_product_categories(username, categories)
    return next(
        item for item in list_product_categories(username)
        if item.get("id") == composite_id
    )


def refresh_product_category_composition(
    username: str,
    category_id: str,
) -> dict[str, Any] | None:
    """Re-resolve and persist a composition from its current parent IDs."""
    raw = str(category_id or "").strip()
    target = get_product_category(username, raw)
    wanted = raw if target is not None else _canonical_category_reference(raw)
    target = target or get_product_category(username, wanted)
    if target is None:
        return None
    if not target.get("is_composite"):
        raise ValueError("只有乘积分类可以从父分类更新内容")
    parents = [
        str(value).strip()
        for value in target.get("parent_category_ids") or []
        if str(value).strip()
    ]
    if len(parents) != 2:
        raise ValueError("产品乘积分类缺少两个父分类")
    from server.modules.products.product_category_paths import compose_category_items

    categories = load_product_categories(username)
    refreshed_items = compose_category_items(parents, username)
    for index, item in enumerate(categories):
        if str(item.get("id") or "") != wanted:
            continue
        updated = dict(item)
        updated["items"] = refreshed_items
        updated["updated_at"] = time.time()
        categories[index] = _normalize_definition(updated)
        save_product_categories(username, categories)
        return get_product_category(username, wanted)
    return None


def delete_product_category(username: str, category_id: str) -> bool:
    wanted = str(category_id or "").strip()
    visible = get_product_category(username, wanted)
    if visible is not None and visible.get("source_managed"):
        raise PermissionError("数据源产品分类由服务器固定提供，不能删除")
    references = product_group_references(username, wanted)
    if references:
        raise ProductCategoryInUseError(wanted, references)
    categories = load_product_categories(username)
    filtered = [item for item in categories if str(item.get("id") or "") != wanted]
    if len(filtered) == len(categories):
        return False
    save_product_categories(username, filtered)
    enqueue_entity(username, "product_category", wanted, {}, deleted=True)
    return True


def update_product_category(
    username: str,
    category_id: str,
    name: str,
    items: list[dict[str, Any]] | None = None,
    *,
    new_category_id: str | None = None,
    is_super_admin: bool = False,
) -> dict[str, Any] | None:
    """Update a category while protecting stable product-group references."""
    raw = str(category_id or "").strip()
    target = get_product_category(username, raw)
    wanted = raw if target is not None else _canonical_category_reference(raw)
    target = target or get_product_category(username, wanted)
    if target is None:
        return None
    title = _category_name(name)
    requested_id = _category_id(new_category_id or wanted)
    if requested_id != wanted:
        raise ValueError("产品分类 ID 由服务器生成且不可修改")

    if target.get("source_managed"):
        if not is_super_admin:
            raise PermissionError("只有超级管理员可以修改数据源产品分类")
        if requested_id != wanted:
            raise ValueError("数据源产品分类 ID 属于固定数据源契约，不能修改")
        _save_source_category_override(wanted, title)
        return get_product_category(username, wanted)

    categories = load_product_categories(username)
    if target.get("is_composite"):
        current_items = _normalize_definition(target).get("items") or []
        if items is not None:
            updated_items = _normalize_composite_label_updates(items, current_items)
            from server.modules.products.product_category_paths import (
                regenerate_generated_others,
            )
            updated_items = regenerate_generated_others(updated_items)
        else:
            updated_items = current_items
        current_title = str(
            target.get("title_zh") or target.get("alias") or wanted
        ).strip()
        if title != current_title:
            raise ValueError("乘积分类标题由父分类生成，只能修改条目标题")
        for index, item in enumerate(categories):
            if str(item.get("id") or "") != wanted:
                continue
            updated = dict(item)
            updated["items"] = updated_items
            updated["updated_at"] = time.time()
            categories[index] = _normalize_definition(updated)
            save_product_categories(username, categories)
            return get_product_category(username, wanted)
        return None
    if any(
        str(item.get("id") or "") != wanted
        and str(item.get("title_zh") or item.get("alias") or "").strip() == title
        for item in list_product_categories(username)
    ):
        raise ValueError("产品分类名称已存在")
    if any(
        str(item.get("id") or "") == requested_id
        and str(item.get("id") or "") != wanted
        for item in categories
    ) or any(
        str(item.get("id") or "") == requested_id
        for item in _source_category_definitions()
    ):
        raise ValueError("产品分类 ID 已存在")

    normalized_items = None
    inferred_source_ids: list[str] | None = None
    if items is not None and not target.get("is_composite"):
        normalized_items = _validate_category_items(_normalize_items(items))
        from server.modules.products.product_category_paths import (
            canonicalize_product_paths,
        )

        normalized_items = [
            {
                **item,
                "paths": canonicalize_product_paths(
                    item["paths"], username=username,
                ),
            }
            for item in normalized_items
        ]
        inferred_source_ids = infer_category_source_ids(normalized_items)
        current_items = _normalize_definition(target).get("items") or []
        _validate_generated_items_unchanged(current_items, normalized_items)
        from server.modules.products.product_category_paths import (
            regenerate_generated_others,
        )
        normalized_items = regenerate_generated_others(normalized_items)

    for index, item in enumerate(categories):
        if str(item.get("id") or "") != wanted:
            continue
        updated = dict(item)
        updated["id"] = requested_id
        updated["alias"] = title
        updated["title_zh"] = title
        updated["updated_at"] = time.time()
        if normalized_items is not None:
            updated["items"] = normalized_items
            updated["source_ids"] = inferred_source_ids or []
        categories[index] = _normalize_definition(updated)
        save_product_categories(username, categories)
        return get_product_category(username, requested_id)
    return None


def infer_category_source_ids(items: list[dict[str, Any]]) -> list[str]:
    """Infer source bundles from all concrete paths in ordinary categories."""
    from server.services.product_catalog_projection import (
        source_ids_for_product_paths,
    )

    paths = [
        path
        for item in items
        for path in item.get("paths") or []
        if not str(path or "").strip().startswith("-")
    ]
    return list(source_ids_for_product_paths(paths))
