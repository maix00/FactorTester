"""Filesystem storage helpers for custom and public factor sources."""

from __future__ import annotations

import os

from server.services.user_storage import user_data_dir


def custom_factor_dir(username: str) -> str:
    directory = os.path.join(user_data_dir(username), 'custom_factors')
    os.makedirs(directory, exist_ok=True)
    return directory


def factor_path(username: str, factor_id: str) -> str:
    return os.path.join(custom_factor_dir(username), f'{factor_id}.py')


def load_factor_source(username: str, factor_id: str) -> str | None:
    path = factor_path(username, factor_id)
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as file:
        return file.read()


def save_factor_source(username: str, factor_id: str, source_code: str) -> None:
    path = factor_path(username, factor_id)
    with open(path, 'w', encoding='utf-8') as file:
        file.write(source_code)


def public_factor_path(factor_id: str) -> str:
    return os.path.join(os.getcwd(), 'Factors', f'{factor_id}.py')


def save_public_factor_source(factor_id: str, source_code: str) -> None:
    path = public_factor_path(factor_id)
    with open(path, 'w', encoding='utf-8') as file:
        file.write(source_code)


def rename_factor_source(username: str, old_factor_id: str, new_factor_id: str) -> bool:
    """Rename a custom factor file (and any companion .json/__pycache__)."""
    old_path = factor_path(username, old_factor_id)
    if not os.path.exists(old_path):
        return False
    new_path = factor_path(username, new_factor_id)
    os.rename(old_path, new_path)

    # Also rename companion .json if present
    old_json = os.path.join(custom_factor_dir(username), f'{old_factor_id}.json')
    if os.path.exists(old_json):
        new_json = os.path.join(custom_factor_dir(username), f'{new_factor_id}.json')
        os.rename(old_json, new_json)

    # Clear __pycache__ to avoid stale .pyc interference
    pycache = os.path.join(custom_factor_dir(username), '__pycache__')
    if os.path.isdir(pycache):
        import shutil
        shutil.rmtree(pycache, ignore_errors=True)

    return True


def delete_factor_source(username: str, factor_id: str) -> bool:
    path = factor_path(username, factor_id)
    if os.path.exists(path):
        os.remove(path)
        return True
    old_path = os.path.join(custom_factor_dir(username), f'{factor_id}.json')
    if os.path.exists(old_path):
        os.remove(old_path)
    return False
