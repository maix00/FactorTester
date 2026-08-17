"""Shared product-category objects, IDs, migrations, and source projections."""

from __future__ import annotations

import re
import time
from hashlib import sha1
from typing import Any


_CATEGORY_NAME = re.compile(r"[^/\\\r\n]{1,120}")
_CATEGORY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@$×-]{0,511}")
_SOURCE_CATEGORY_OWNER = "__server_product_category_overrides__"
_GENERATED_LABEL = "Others"


def migrate_legacy_category_id(value: object) -> str:
    """Map retired provider IDs during the one-time local migration only."""
    from server.modules.shared.price_services import (
        CN_FUTURES_COMPOSITE_CATEGORY_ID,
        CN_FUTURES_DAY_NIGHT_CATEGORY_ID,
        CN_FUTURES_SECTOR_CATEGORY_ID,
    )

    return {
        "day_night": CN_FUTURES_DAY_NIGHT_CATEGORY_ID,
        "sector": CN_FUTURES_SECTOR_CATEGORY_ID,
        "day_night_x_sector": CN_FUTURES_COMPOSITE_CATEGORY_ID,
        "sector_x_day_night": CN_FUTURES_COMPOSITE_CATEGORY_ID,
        "cnfutures_day_night_x_cnfutures_sector": CN_FUTURES_COMPOSITE_CATEGORY_ID,
        "cnfutures_sector_x_cnfutures_day_night": CN_FUTURES_COMPOSITE_CATEGORY_ID,
    }.get(str(value or "").strip(), str(value or "").strip())


def migrate_legacy_category_path(value: object) -> str:
    """Migrate an old explicit tree prefix before normal path validation."""
    raw = str(value or "").strip()
    negative = raw.startswith("-")
    path = raw[1:].strip() if negative else raw
    parts = path.strip("/").split("/") if path else []
    if len(parts) >= 3 and parts[0] == "ProductCategory":
        parts[1] = migrate_legacy_category_id(parts[1])
        path = "/".join(parts)
    return f"-{path}" if negative else path


def migrate_owned_category_id(username: str, value: object) -> str:
    """Migrate one stored user-category reference to the owner's namespace."""
    return _migrate_user_category_id(username, value)


def migrate_owned_category_path(username: str, value: object) -> str:
    """Migrate a stored category-qualified path for one account."""
    migrated = migrate_legacy_category_path(value)
    raw = str(migrated or "").strip()
    negative = raw.startswith("-")
    path = raw[1:].strip() if negative else raw
    parts = path.strip("/").split("/") if path else []
    if len(parts) >= 3 and parts[0] == "ProductCategory":
        parts[1] = _migrate_user_category_id(username, parts[1])
        path = "/".join(parts)
    return f"-{path}" if negative else path


def category_name(value: object) -> str:
    title = str(value or "").strip()
    if not _CATEGORY_NAME.fullmatch(title):
        raise ValueError("产品分类名称不能为空，且不能包含路径分隔符")
    return title


def canonical_category_reference(value: object) -> str:
    """Return a current fixed source ID or an unchanged user category ID."""
    raw = str(value or "").strip()
    if not raw:
        return raw
    from server.modules.shared.price_services import normalize_product_category_id

    try:
        return normalize_product_category_id(raw)
    except ValueError:
        # User-owned IDs are deliberately not passed through the provider
        # alias normalizer. They are exact, owner-prefixed identifiers.
        return raw


def category_id(value: object) -> str:
    identifier = str(value or "").strip()
    if not identifier or not _CATEGORY_ID.fullmatch(identifier):
        raise ValueError(
            "产品分类 ID 只能包含字母、数字、点、冒号、下划线、乘号或短横线"
        )
    return identifier


def composite_category_id(parent_ids: list[str] | tuple[str, ...]) -> str:
    """Build the stable ID for one pair of parent categories.

    The pair itself is the identity.  Sorting makes ``A×B`` and ``B×A`` the
    same registered category, so creating the same product-category
    composition twice cannot produce duplicate rows with different random
    IDs.
    """
    values = tuple(sorted({str(value or "").strip() for value in parent_ids}))
    if len(values) != 2:
        raise ValueError("乘积分类必须绑定两个不同的父分类")
    return category_id("×".join(values))


def new_user_category_id(username: str, seed: str = "") -> str:
    owner = str(username or "").strip()
    if not owner or "/" in owner or "\\" in owner:
        raise ValueError("用户身份不能用于生成产品分类 ID")
    digest = sha1(
        f"{owner}:{seed}:{time.time_ns()}".encode("utf-8")
    ).hexdigest()[:16]
    return category_id(f"{owner}:category_{digest}")


def normalize_items(value: object) -> list[dict[str, Any]]:
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
        item = {"label": label, "paths": normalized_paths}
        # ``Others`` is a complement generated by Category.  Preserve the
        # marker in the shared category object so every editor can enforce
        # the same read-only contract instead of treating it as user input.
        if bool(raw.get("label_generated")) or label == _GENERATED_LABEL:
            item["label_generated"] = True
        result.append(item)
    return result


def is_generated_label(item: dict[str, Any] | None) -> bool:
    """Return whether a label is generated by the category engine."""
    if not isinstance(item, dict):
        return False
    return bool(item.get("label_generated")) or str(
        item.get("label") or item.get("title") or ""
    ).strip() == _GENERATED_LABEL


def validate_generated_items_unchanged(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> None:
    """Protect generated labels, IDs, and paths during ordinary edits.

    Label IDs are assigned from row order, so keeping a generated row at the
    same index also prevents an otherwise implicit ID change.  The explicit
    position check rejects deletion, reordering, renaming, and path edits.
    """
    for index, current in enumerate(existing):
        if not is_generated_label(current):
            continue
        if index >= len(incoming):
            raise ValueError("Others 标签由系统自动生成，不能修改")
        submitted = incoming[index]
        current_label = str(current.get("label") or "").strip()
        submitted_label = str(submitted.get("label") or "").strip()
        current_paths = [
            str(path).strip() for path in current.get("paths") or []
        ]
        submitted_paths = [
            str(path).strip() for path in submitted.get("paths") or []
        ]
        if submitted_label != current_label or submitted_paths != current_paths:
            raise ValueError("Others 标签由系统自动生成，不能修改")
    for index, submitted in enumerate(incoming):
        if is_generated_label(submitted) and (
            index >= len(existing) or not is_generated_label(existing[index])
        ):
            raise ValueError("Others 标签由系统自动生成，不能由客户端新增")


def normalize_composite_label_updates(
    value: object,
    existing: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Update only labels while keeping a composite's server paths immutable."""
    if not isinstance(value, list) or len(value) != len(existing):
        raise ValueError("乘积分类只能修改已有条目的标题，不能增删条目")
    labels: set[str] = set()
    result: list[dict[str, Any]] = []
    for raw, current in zip(value, existing, strict=True):
        if not isinstance(raw, dict):
            raise ValueError("乘积分类条目格式无效")
        label = str(raw.get("label") or raw.get("title") or "").strip()
        if not label or label in labels:
            raise ValueError("乘积分类条目标题不能为空且不能重复")
        if label == _GENERATED_LABEL and not is_generated_label(current):
            raise ValueError("Others 是保留标签，不能作为普通 Label 标题")
        if is_generated_label(current) and label != str(
            current.get("label") or ""
        ).strip():
            raise ValueError("Others 标签由系统自动生成，不能修改")
        if "paths" in raw:
            submitted = raw.get("paths")
            if isinstance(submitted, str):
                submitted = submitted.splitlines()
            submitted = [
                str(path).strip()
                for path in submitted or []
                if str(path).strip()
            ]
            current_paths = [
                str(path).strip() for path in current.get("paths") or []
                if str(path).strip()
            ]
            if submitted != current_paths:
                raise ValueError("乘积分类的产品路径只能查看，不能修改")
        labels.add(label)
        item = {"label": label, "paths": list(current.get("paths") or [])}
        if is_generated_label(current):
            item["label_generated"] = True
        result.append(item)
    return result


def normalize_definition(value: dict[str, Any]) -> dict[str, Any]:
    """Normalize one source or user category into the shared JSON shape."""
    result = dict(value)
    result["id"] = category_id(result.get("id"))
    result["alias"] = str(
        result.get("alias") or result.get("title_zh") or result["id"]
    )
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
        migrate_legacy_category_id(item)
        for item in result.get("parent_category_ids") or []
        if str(item).strip()
    ))
    result["items"] = with_label_ids(
        normalize_items(result["items"]) if result.get("items") else [],
        result["id"],
    )
    result["composable"] = bool(result.get("composable", True))
    result["is_composite"] = bool(result.get("is_composite", False))
    return result


def category_view(
    value: dict[str, Any],
    *,
    kind: str,
    owner_ref: str,
    source_managed: bool,
) -> dict[str, Any]:
    """Return one JSON-ready category object for every category origin."""
    result = normalize_definition(value)
    result.update({
        "kind": kind,
        "owner_ref": owner_ref,
        "source_managed": bool(source_managed),
    })
    return result


def with_label_ids(
    items: list[dict[str, Any]],
    category_ref: str,
) -> list[dict[str, Any]]:
    """Generate label IDs from the category ID and stable row ordinal."""
    return [
        {**item, "label_id": f"{category_ref}_{index}"}
        for index, item in enumerate(items, start=1)
    ]


def migrate_owned_definition(
    item: dict[str, Any],
    username: str,
) -> dict[str, Any]:
    value = dict(item)
    value["id"] = _migrate_user_category_id(username, value.get("id"))
    value["parent_category_ids"] = [
        _migrate_user_category_id(username, item_id)
        for item_id in value.get("parent_category_ids") or []
    ]
    if value.get("is_composite") and len(value["parent_category_ids"]) == 2:
        # Older versions generated a random owner-prefixed ID for a
        # composition.  The parent pair is now the canonical identity.
        value["id"] = composite_category_id(value["parent_category_ids"])
    value["items"] = [
        {
            **dict(entry),
            "paths": [migrate_owned_category_path(username, path)
                      for path in entry.get("paths") or []],
        }
        for entry in value.get("items") or []
        if isinstance(entry, dict)
    ]
    return value


def _migrate_user_category_id(username: str, value: object) -> str:
    migrated = migrate_legacy_category_id(value)
    if migrated != str(value or "").strip():
        return migrated
    raw = str(value or "").strip()
    if not raw or _is_provider_category_id(raw):
        return raw
    owner = str(username or "").strip()
    if not owner or "/" in owner or "\\" in owner:
        return raw
    if raw.startswith(f"{owner}:"):
        return raw
    return f"{owner}:{raw}"


def _is_provider_category_id(value: object) -> bool:
    from server.modules.shared.price_services import (
        CN_FUTURES_COMPOSITE_CATEGORY_ID,
        available_product_categories,
    )

    wanted = str(value or "").strip()
    return wanted == CN_FUTURES_COMPOSITE_CATEGORY_ID or wanted in {
        str(item.get("id") or "")
        for item in available_product_categories()
    }


def load_source_category_overrides() -> dict[str, dict[str, Any]]:
    from tools.data.sqlite.account_manager.product_category import (
        load_product_categories as load_rows,
        save_product_categories as save_rows,
    )

    raw = load_rows(_SOURCE_CATEGORY_OWNER)
    migrated = []
    for item in raw:
        value = dict(item)
        value["id"] = migrate_legacy_category_id(value.get("id"))
        migrated.append(value)
    if migrated != raw:
        save_rows(_SOURCE_CATEGORY_OWNER, migrated)
    return {
        str(item.get("id") or ""): item
        for item in migrated
        if str(item.get("id") or "").strip()
    }


def save_source_category_override(category_ref: str, title: str) -> None:
    from tools.data.sqlite.account_manager.product_category import (
        load_product_categories as load_rows,
        save_product_categories as save_rows,
    )

    overrides = load_rows(_SOURCE_CATEGORY_OWNER)
    next_value = {
        "id": category_ref,
        "alias": title,
        "title_zh": title,
        "kind": "source_override",
        "updated_at": time.time(),
    }
    for index, item in enumerate(overrides):
        if str(item.get("id") or "") == category_ref:
            overrides[index] = next_value
            break
    else:
        overrides.append(next_value)
    save_rows(_SOURCE_CATEGORY_OWNER, overrides)


def source_category_items(category_id: str) -> list[dict[str, Any]]:
    """Project provider labels with stable category-scoped label IDs."""
    from server.modules.products.product_category_paths import category_tree
    from server.modules.shared.price_services import (
        CN_FUTURES_COMPOSITE_CATEGORY_ID,
        CN_FUTURES_DAY_NIGHT_CATEGORY_ID,
        CN_FUTURES_SECTOR_CATEGORY_ID,
    )

    tree_titles = {
        CN_FUTURES_DAY_NIGHT_CATEGORY_ID: "日夜盘",
        CN_FUTURES_SECTOR_CATEGORY_ID: "行业",
        CN_FUTURES_COMPOSITE_CATEGORY_ID: "日夜盘×行业",
    }
    wanted = tree_titles.get(str(category_id or ""))
    if not wanted:
        return []
    tree = category_tree(category_id)
    paths_by_label: dict[str, set[str]] = {}

    def walk(value: Any, path: list[str]) -> None:
        if not isinstance(value, dict):
            return
        for key, child in value.items():
            if key in {"$OBJECTS$", "$SUBCLASS$"}:
                if key == "$SUBCLASS$":
                    walk(child, path)
                continue
            title = key.__name__ if isinstance(key, type) else str(key)
            next_path = [*path, title]
            if title == wanted and isinstance(child, dict):
                for label_key in child:
                    if label_key in {"$OBJECTS$", "$SUBCLASS$"}:
                        continue
                    label = (
                        label_key.__name__ if isinstance(label_key, type)
                        else str(label_key)
                    )
                    paths_by_label.setdefault(label, set()).add(
                        "/".join([*next_path, label])
                    )
            if isinstance(child, dict):
                walk(child, next_path)

    walk(tree, [])
    result = []
    for index, (label, paths) in enumerate(
        sorted(paths_by_label.items(), key=lambda item: item[0]),
        start=1,
    ):
        item = {
            "label_id": f"{category_id}_{index}",
            "label": label,
            "paths": sorted(paths),
        }
        if label == _GENERATED_LABEL:
            item["label_generated"] = True
        result.append(item)
    return result


def source_category_definitions() -> list[dict[str, Any]]:
    from server.modules.shared.price_services import available_product_categories

    return available_product_categories()


def shared_source_ids(
    parents: list[dict[str, Any] | None],
) -> list[str]:
    """Return data-source bundles shared by every parent category."""
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
