"""Filesystem storage helpers for per-user server data."""

from __future__ import annotations

import json
import os
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
    """Return the JSON path for a user's template collection."""
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
