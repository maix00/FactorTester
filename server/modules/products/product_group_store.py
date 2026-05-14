"""Product group (产品组) storage helpers.

A product_group is a named collection of product paths: { name, paths: [...], updated_at }.
Storage: {user_data}/product_groups.json  (single JSON array per user)
"""
from __future__ import annotations

import json
import os
import time

from server.services.user_storage import user_data_dir


def _groups_path(username: str) -> str:
    return os.path.join(user_data_dir(username), 'product_groups.json')


def load_product_groups(username: str) -> list:
    path = _groups_path(username)
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, list):
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
