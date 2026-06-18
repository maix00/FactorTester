"""SQLite access for account management domain tables."""

from __future__ import annotations

import settings as Settings
from tools.data.sqlite.db import connect_sqlite

from .user import load_accounts, save_accounts, ensure_user_schema
from .user_level import (
    load_levels,
    load_organizations,
    save_levels,
    save_organizations,
    ensure_user_level_schema,
)
from .product_group import (
    ensure_product_group_schema,
    load_product_groups,
    save_product_groups,
)
from .param_config import (
    DEFAULT_SCOPE_KEY,
    delete_param_config,
    delete_scope,
    ensure_param_config_schema,
    ensure_scope_exists,
    list_all_aliases_across_scopes,
    list_param_config_aliases,
    list_param_config_scopes,
    load_param_config,
    normalize_product_group,
    rename_scope,
    save_param_config,
    save_param_config_payload,
)
from .user_template import (
    delete_user_template_collections,
    delete_user_template_collection,
    iter_user_template_collections,
    load_user_templates,
    save_user_template_payload,
    save_user_templates,
    ensure_user_template_schema,
)


def ensure_account_manager_sqlite_store() -> str:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_user_schema(conn)
        ensure_user_level_schema(conn)
        ensure_product_group_schema(conn)
        ensure_param_config_schema(conn)
        ensure_user_template_schema(conn)
    return str(Settings.CACHE_DB_PATH)


def sync_account_manager_sqlite_store() -> str:
    return ensure_account_manager_sqlite_store()
