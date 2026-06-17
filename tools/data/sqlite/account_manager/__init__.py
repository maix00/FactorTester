"""SQLite access for account management domain tables."""

from __future__ import annotations

import Settings
from tools.data.sqlite.db import connect_sqlite

from .user import load_accounts, save_accounts, ensure_user_schema
from .user_level import (
    load_levels,
    load_organizations,
    save_levels,
    save_organizations,
    ensure_user_level_schema,
)
from .user_template import (
    delete_user_template_collections,
    delete_user_template_collection,
    iter_user_template_collections,
    load_user_templates,
    save_user_templates,
    ensure_user_template_schema,
)


def ensure_account_manager_sqlite_store() -> str:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_user_schema(conn)
        ensure_user_level_schema(conn)
        ensure_user_template_schema(conn)
    return str(Settings.CACHE_DB_PATH)


def sync_account_manager_sqlite_store() -> str:
    return ensure_account_manager_sqlite_store()
