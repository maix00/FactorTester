"""Local per-user file roots for resources that have not moved to SQLite."""

from __future__ import annotations

import os

from scripts.data_dir import DATA_DIR as _DATA_DIR
USER_STORAGE_DIR = os.path.join(_DATA_DIR, 'user_storage')


def user_data_dir(username: str) -> str:
    directory = os.path.join(USER_STORAGE_DIR, username)
    os.makedirs(directory, exist_ok=True)
    return directory
