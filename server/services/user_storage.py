"""Filesystem storage helpers for per-user server data."""

from __future__ import annotations

import json
import os
import shutil
import time


DATA_DIR = os.path.abspath(os.path.join(os.getcwd(), '..', 'data'))
USERS_DIR = os.path.join(DATA_DIR, 'users')


def user_data_dir(username: str) -> str:
    directory = os.path.join(USERS_DIR, username)
    os.makedirs(directory, exist_ok=True)
    return directory


def user_template_path(
    username: str,
    kind: str,
    ff_alias: str | None = None,
    scope_key: str | None = None,
) -> str:
    """Return the JSON path for a user's template collection.

    `scope_key` is the storage-level isolation key. Different modules may choose
    different meanings for it, e.g. a single-factor-test FactorFamily alias or a
    factor-library user_id. Keep this helper business-agnostic.
    """
    directory = user_data_dir(username)
    if scope_key:
        directory = os.path.join(directory, f'{kind}_templates')
        os.makedirs(directory, exist_ok=True)
        return os.path.join(directory, f'{scope_key}.json')
    if kind == 'params' and ff_alias:
        directory = os.path.join(directory, 'params_templates')
        os.makedirs(directory, exist_ok=True)
        return os.path.join(directory, f'{ff_alias}.json')
    return os.path.join(directory, f'{kind}_templates.json')


def load_user_templates(
    username: str,
    kind: str,
    ff_alias: str | None = None,
    scope_key: str | None = None,
) -> list:
    path = user_template_path(username, kind, ff_alias, scope_key=scope_key)
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as file:
                data = json.load(file)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def save_user_templates(
    username: str,
    kind: str,
    templates: list,
    ff_alias: str | None = None,
    scope_key: str | None = None,
) -> None:
    path = user_template_path(username, kind, ff_alias, scope_key=scope_key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as file:
        json.dump(templates, file, ensure_ascii=False, indent=2)


def new_template_id() -> str:
    return str(int(time.time() * 1000))


def archive_user_dir(username: str) -> str | None:
    """Move a user's storage directory into archive with timestamp suffix.

    Returns archived directory path when moved, else None when source doesn't exist.
    """
    src = os.path.join(USERS_DIR, username)
    if not os.path.isdir(src):
        return None
    archive_root = os.path.join(USERS_DIR, '_archived')
    os.makedirs(archive_root, exist_ok=True)
    timestamp = time.strftime('%Y%m%d_%H%M%S')
    dst = os.path.join(archive_root, f'{username}__{timestamp}')
    suffix = 1
    while os.path.exists(dst):
        suffix += 1
        dst = os.path.join(archive_root, f'{username}__{timestamp}_{suffix}')
    shutil.move(src, dst)
    return dst
