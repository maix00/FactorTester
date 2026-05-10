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


def delete_factor_source(username: str, factor_id: str) -> bool:
    path = factor_path(username, factor_id)
    if os.path.exists(path):
        os.remove(path)
        return True
    old_path = os.path.join(custom_factor_dir(username), f'{factor_id}.json')
    if os.path.exists(old_path):
        os.remove(old_path)
    return False
