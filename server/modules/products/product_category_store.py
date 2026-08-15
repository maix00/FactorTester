"""Account-owned product category definitions and catalog projections."""

from __future__ import annotations

import re
import time
from hashlib import sha1
from typing import Any

from tools.data.account_manage import (
    load_product_categories,
    save_product_categories,
)
from tools.data.sqlite.account_manager.domain_sync import enqueue_entity


_CATEGORY_NAME = re.compile(r"[^/\\\r\n]{1,120}")


def list_product_categories(username: str) -> list[dict[str, Any]]:
    """Return source categories followed by categories owned by ``username``."""
    from server.modules.shared.price_services import available_product_categories

    source = []
    for item in available_product_categories():
        value = dict(item)
        value.update({
            "kind": "source",
            "owner_ref": "source",
            "source_managed": True,
            "items": list(value.get("items") or []),
        })
        source.append(value)
    owned = []
    for item in load_product_categories(username):
        value = _normalize_definition(item)
        value["owner_ref"] = f"user:{username}"
        value["source_managed"] = False
        owned.append(value)
    return source + owned


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
) -> dict[str, Any]:
    title = _category_name(name)
    normalized_items = _normalize_items(items)
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
    categories = load_product_categories(username)
    if any(
        str(item.get("title_zh") or item.get("alias") or "").strip() == title
        for item in list_product_categories(username)
    ):
        raise ValueError("产品分类名称已存在")
    category = _normalize_definition({
        "id": f"category_{sha1(f'{username}:{time.time_ns()}'.encode()).hexdigest()[:16]}",
        "alias": title,
        "title_zh": title,
        "dimensions": [],
        "source_ids": [],
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
    selected = list(dict.fromkeys(
        str(value or "").strip() for value in category_ids
        if str(value or "").strip()
    ))
    if len(selected) != 2:
        raise ValueError("请选择两个不同的分类")
    definitions = {
        str(item.get("id") or ""): item
        for item in list_product_categories(username)
    }
    parents = [definitions.get(value) for value in selected]
    if any(item is None for item in parents):
        raise ValueError("所选分类已不存在")
    if any(not item.get("composable", True) for item in parents if item):
        raise ValueError("所选分类不能参与乘积")

    # Provider categories already have a canonical tree implementation.  Keep
    # that stable ID so the tree renderer can use it; custom compositions use
    # a content-derived ID and retain their parent references.
    composite_id = _source_composite_id(selected)
    if composite_id is None:
        composite_id = "category_" + sha1(
            "×".join(sorted(selected)).encode("utf-8")
        ).hexdigest()[:16]
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
    category = _normalize_definition({
        "id": composite_id,
        "alias": "×".join(labels),
        "title_zh": "×".join(labels),
        "dimensions": list(dict.fromkeys(dimensions)),
        "source_ids": source_ids,
        "composable": True,
        "is_composite": True,
        "parent_category_ids": selected,
        "items": _compose_items(parents),
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


def delete_product_category(username: str, category_id: str) -> bool:
    wanted = str(category_id or "").strip()
    categories = load_product_categories(username)
    filtered = [item for item in categories if str(item.get("id") or "") != wanted]
    if len(filtered) == len(categories):
        return False
    save_product_categories(username, filtered)
    enqueue_entity(username, "product_category", wanted, {}, deleted=True)
    return True


def _source_composite_id(category_ids: list[str]) -> str | None:
    source_ids = {"day_night", "sector"}
    if not set(category_ids).issubset(source_ids):
        return None
    order = ("day_night", "sector")
    return "_x_".join(item for item in order if item in set(category_ids))


def _compose_items(parents: list[dict[str, Any] | None]) -> list[dict[str, Any]]:
    """Intersect explicit path sets for user-owned category compositions."""
    if len(parents) != 2 or any(not item or not item.get("items") for item in parents):
        return []
    left, right = (parents[0].get("items") or []), (parents[1].get("items") or [])
    result = []
    for left_item in left:
        for right_item in right:
            paths = []
            for left_path in left_item.get("paths") or []:
                for right_path in right_item.get("paths") or []:
                    if left_path == right_path:
                        paths.append(left_path)
                    elif left_path.startswith(f"{right_path}/"):
                        paths.append(left_path)
                    elif right_path.startswith(f"{left_path}/"):
                        paths.append(right_path)
            if paths:
                result.append({
                    "label": f"({left_item.get('label')}×{right_item.get('label')})",
                    "paths": list(dict.fromkeys(paths)),
                })
    return result


def _category_name(value: object) -> str:
    title = str(value or "").strip()
    if not _CATEGORY_NAME.fullmatch(title):
        raise ValueError("产品分类名称不能为空，且不能包含路径分隔符")
    return title


def _normalize_items(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError("产品分类至少需要一个条目")
    result = []
    labels = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise ValueError("产品分类条目格式无效")
        label = str(raw.get("label") or raw.get("title") or "").strip()
        paths = raw.get("paths")
        if isinstance(paths, str):
            paths = paths.splitlines()
        if not label or label in labels:
            raise ValueError("产品分类条目标签不能为空且不能重复")
        if not isinstance(paths, list):
            raise ValueError("产品路径必须按行填写")
        normalized_paths = list(dict.fromkeys(
            str(path).strip() for path in paths if str(path).strip()
        ))
        if not normalized_paths:
            raise ValueError(f"分类条目“{label}”至少需要一条产品路径")
        labels.add(label)
        result.append({"label": label, "paths": normalized_paths})
    return result


def _normalize_definition(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    result["id"] = str(result.get("id") or "").strip()
    result["alias"] = str(result.get("alias") or result.get("title_zh") or result["id"])
    result["title_zh"] = str(result.get("title_zh") or result["alias"])
    result["dimensions"] = list(dict.fromkeys(
        str(item).strip() for item in result.get("dimensions") or []
        if str(item).strip()
    ))
    result["source_ids"] = list(dict.fromkeys(
        str(item).strip() for item in result.get("source_ids") or []
        if str(item).strip()
    ))
    result["parent_category_ids"] = list(dict.fromkeys(
        str(item).strip() for item in result.get("parent_category_ids") or []
        if str(item).strip()
    ))
    result["items"] = _normalize_items(result["items"]) if result.get("items") else []
    result["composable"] = bool(result.get("composable", True))
    result["is_composite"] = bool(result.get("is_composite", False))
    return result


def _shared_source_ids(parents: list[dict[str, Any] | None]) -> list[str]:
    """Return source identities shared by every parent category.

    A source identity is a data-source bundle, not a server identity.  The
    federated catalog separately records all online servers that provide the
    same bundle.
    """
    sets = [
        {
            str(value).strip()
            for value in item.get("source_ids") or []
            if str(value).strip()
        }
        for item in parents
        if item is not None
    ]
    if not sets:
        return []
    return sorted(set.intersection(*sets))
