"""Product group storage helpers backed by SQLite."""

from __future__ import annotations

import time
import uuid
from hashlib import sha1

from server.modules.products.product_path_selection import resolve_selection_products
from server.modules.shared.submission_model import ProductPathSelection
from tools.data.account_manage import load_product_groups as _load_product_groups
from tools.data.account_manage import save_product_groups as _save_product_groups


def _resolve_group_products(paths: list) -> list:
    from server.modules.shared.price_services import cached_product_tree

    tree = cached_product_tree().tree
    _, products = resolve_selection_products(paths, tree)
    return [getattr(product, "name", str(product)) for product in products]


def load_product_groups(username: str) -> list:
    groups = _load_product_groups(username)
    dirty = False
    for group in groups:
        if "id" not in group:
            group["id"] = _legacy_group_id(group.get("name"))
            dirty = True
        if "product_names" not in group:
            _enrich_group(group)
            dirty = True
    if dirty:
        save_product_groups(username, groups)
    return groups


def save_product_groups(username: str, groups: list) -> None:
    _save_product_groups(username, groups)


def find_group_by_name(groups: list, name: str) -> int:
    for i, group in enumerate(groups):
        if group.get("name") == name:
            return i
    return -1


def find_group_by_paths(groups: list, paths: list) -> dict | None:
    wanted = {str(path) for path in paths if str(path).strip()}
    for group in groups:
        current = {str(path) for path in group.get("paths", []) if str(path).strip()}
        if current == wanted:
            return group
    return None


def product_group_to_path_selection(
    group: dict,
    *,
    selection_id: str | None = None,
    page_uuid: str = "",
) -> ProductPathSelection:
    """Build the backend product-path selection that corresponds to one template row."""
    name = str(group.get("name") or group.get("product_group") or "").strip()
    if not name:
        raise AssertionError("产品组模板缺少名称")
    return ProductPathSelection.from_product_group_template(
        selection_id or str(group.get("id") or name),
        group,
        page_uuid=page_uuid,
    )


def _enrich_group(group: dict) -> dict:
    paths = group.get("paths", [])
    group["path_count"] = len(paths)
    try:
        group["product_names"] = _resolve_group_products(paths)
        group["product_count"] = len(group["product_names"])
    except Exception:
        group["product_names"] = []
        group["product_count"] = 0
    return group


def create_product_group(username: str, name: str, paths: list) -> dict | None:
    name = name.strip()
    if not name:
        return None
    groups = load_product_groups(username)
    if find_group_by_name(groups, name) >= 0:
        return None
    group = {
        "id": f"pg_{uuid.uuid4().hex[:12]}",
        "name": name,
        "paths": [path for path in paths if isinstance(path, str) and path.strip()],
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
    }
    groups.append(_enrich_group(group))
    save_product_groups(username, groups)
    return group


def update_product_group(username: str, name: str, paths: list = None) -> dict | None:
    groups = load_product_groups(username)
    idx = find_group_by_name(groups, name)
    if idx < 0:
        return None
    group = groups[idx]
    if paths is not None:
        group["paths"] = [path for path in paths if isinstance(path, str) and path.strip()]
        groups[idx] = _enrich_group(group)
    groups[idx]["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    save_product_groups(username, groups)
    return groups[idx]


def delete_product_group(username: str, name: str) -> bool:
    groups = load_product_groups(username)
    idx = find_group_by_name(groups, name)
    if idx < 0:
        return False
    groups.pop(idx)
    save_product_groups(username, groups)
    return True


def _legacy_group_id(name: object) -> str:
    raw = str(name or "").strip() or "unnamed"
    return f"pg_{sha1(raw.encode('utf-8')).hexdigest()[:12]}"


def rename_product_group(username: str, old_name: str, new_name: str) -> dict | None:
    new_name = new_name.strip()
    if not new_name:
        return None
    groups = load_product_groups(username)
    idx = find_group_by_name(groups, old_name)
    if idx < 0:
        return None
    if old_name != new_name and find_group_by_name(groups, new_name) >= 0:
        return None
    groups[idx]["name"] = new_name
    groups[idx]["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    save_product_groups(username, groups)
    return groups[idx]


def reorder_product_groups(username: str, names: list) -> bool:
    groups = load_product_groups(username)
    group_by_name = {group.get("name"): group for group in groups}
    reordered = [group_by_name[name] for name in names if name in group_by_name]
    if len(reordered) != len(groups):
        return False
    save_product_groups(username, reordered)
    return True
