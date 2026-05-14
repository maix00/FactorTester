"""Product group (产品组) storage helpers.

A product_group is a named collection of tree paths: { name, paths: [...], updated_at }.
Paths are tree node keys (e.g. "单因子测试/农产品/豆类"), resolved to products on read.
Storage: {user_data}/product_groups.json  (single JSON array per user)
"""
from __future__ import annotations

import json
import os
import time

from server.services.product_tree import get_minimal_paths
from server.services.user_storage import user_data_dir


def _resolve_group_products(paths: list) -> list:
    """Resolve tree paths to deduped product objects. Returns product name strings."""
    from server.modules.shared.price_services import cached_product_tree
    from server.services.product_tree import find_node_by_path
    minimal = get_minimal_paths([p for p in paths if isinstance(p, str) and p.strip()])
    tree = cached_product_tree().tree
    products = []
    for path in minimal:
        node = find_node_by_path(tree, path.split('/'))
        if isinstance(node, dict) and '$OBJECTS$' in node and isinstance(node['$OBJECTS$'], list):
            products.extend(node['$OBJECTS$'])
        elif node is not None:
            products.append(node)
    # 去重并返回产品名
    seen = set()
    result = []
    for p in products:
        name = getattr(p, 'name', str(p))
        if name not in seen:
            seen.add(name)
            result.append(name)
    return sorted(result)


def _groups_path(username: str) -> str:
    return os.path.join(user_data_dir(username), 'product_groups.json')


def load_product_groups(username: str) -> list:
    path = _groups_path(username)
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, list):
                dirty = False
                for g in data:
                    if 'product_names' not in g:
                        _enrich_group(g)
                        dirty = True
                if dirty:
                    save_product_groups(username, data)
                return data
    except Exception:
        pass
    return []


def save_product_groups(username: str, groups: list) -> None:
    path = _groups_path(username)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(groups, f, ensure_ascii=False, indent=2)


def find_group_by_name(groups: list, name: str) -> int:
    """Return index of group with given name, or -1."""
    for i, g in enumerate(groups):
        if g.get('name') == name:
            return i
    return -1


def _enrich_group(group: dict) -> dict:
    """Attach path_count, product_names, product_count to a group dict."""
    paths = group.get('paths', [])
    group['path_count'] = len(paths)
    try:
        group['product_names'] = _resolve_group_products(paths)
        group['product_count'] = len(group['product_names'])
    except Exception:
        group['product_names'] = []
        group['product_count'] = 0
    return group


def create_product_group(username: str, name: str, paths: list) -> dict | None:
    name = name.strip()
    if not name:
        return None
    groups = load_product_groups(username)
    if find_group_by_name(groups, name) >= 0:
        return None  # duplicate
    group = {
        'name': name,
        'paths': [p for p in paths if isinstance(p, str) and p.strip()],
        'updated_at': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime()),
    }
    group = _enrich_group(group)  # 固化 product_names/product_count
    groups.append(group)
    save_product_groups(username, groups)
    return group


def update_product_group(username: str, name: str, paths: list = None) -> dict | None:
    groups = load_product_groups(username)
    idx = find_group_by_name(groups, name)
    if idx < 0:
        return None
    group = groups[idx]
    if paths is not None:
        group['paths'] = [p for p in paths if isinstance(p, str) and p.strip()]
        group = _enrich_group(group)  # 重新解析
        groups[idx] = group
    group['updated_at'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    save_product_groups(username, groups)
    return group


def delete_product_group(username: str, name: str) -> bool:
    groups = load_product_groups(username)
    idx = find_group_by_name(groups, name)
    if idx < 0:
        return False
    groups.pop(idx)
    save_product_groups(username, groups)
    return True


def rename_product_group(username: str, old_name: str, new_name: str) -> dict | None:
    new_name = new_name.strip()
    if not new_name:
        return None
    groups = load_product_groups(username)
    idx = find_group_by_name(groups, old_name)
    if idx < 0:
        return None
    if old_name != new_name and find_group_by_name(groups, new_name) >= 0:
        return None  # duplicate
    groups[idx]['name'] = new_name
    groups[idx]['updated_at'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    save_product_groups(username, groups)
    return groups[idx]


def reorder_product_groups(username: str, names: list) -> bool:
    groups = load_product_groups(username)
    name_to_group = {g.get('name'): g for g in groups}
    reordered = [name_to_group[n] for n in names if n in name_to_group]
    if len(reordered) != len(groups):
        return False
    save_product_groups(username, reordered)
    return True
