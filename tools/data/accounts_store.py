"""Filesystem helpers for accounts, organizations, and levels data."""

from __future__ import annotations

import json
import os
from typing import Any

from scripts.data_dir import DATA_DIR

USERS_DIR = os.path.join(DATA_DIR, "users")
ACCOUNTS_FILE = os.path.join(USERS_DIR, "accounts.json")
ORGANIZATIONS_FILE = os.path.join(USERS_DIR, "organizations.json")
LEVELS_FILE = os.path.join(USERS_DIR, "levels.json")


def _read_json(path: str) -> list[dict[str, Any]]:
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as file:
                data = json.load(file)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def load_accounts() -> list[dict[str, Any]]:
    return _read_json(ACCOUNTS_FILE)


def load_organizations() -> list[dict[str, Any]]:
    return _read_json(ORGANIZATIONS_FILE)


def load_levels() -> list[dict[str, Any]]:
    return _read_json(LEVELS_FILE)


def account_display_name(account: dict | None) -> str:
    if not account:
        return ""
    return str(account.get("alias") or account.get("username") or "")
