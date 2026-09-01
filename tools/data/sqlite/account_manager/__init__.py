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
from .product_category import (
    ensure_product_category_schema,
    load_product_categories,
    save_product_categories,
)
from .factor_set import (
    delete_factor_set,
    ensure_factor_set_schema,
    get_factor_set,
    list_factor_sets,
    save_factor_set,
)
from .factor_param_config import (
    DEFAULT_SCOPE_KEY,
    delete_factor_param_config,
    delete_factor_family_configs,
    delete_scope,
    ensure_factor_param_config_schema,
    ensure_scope_exists,
    list_all_factor_param_aliases_across_scopes,
    list_factor_param_config_aliases,
    list_factor_param_config_scopes,
    load_factor_param_config,
    normalize_product_group,
    rename_scope,
    save_factor_param_config,
    save_factor_param_config_payload,
)
from .factor_research_result import (
    config_hash as factor_research_config_hash,
    delete_factor_research_run,
    ensure_factor_research_result_schema,
    list_factor_research_runs,
    save_factor_research_run,
)
def ensure_account_manager_sqlite_store() -> str:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_user_schema(conn)
        ensure_user_level_schema(conn)
        ensure_product_group_schema(conn)
        ensure_product_category_schema(conn)
        ensure_factor_set_schema(conn)
        ensure_factor_param_config_schema(conn)
        ensure_factor_research_result_schema(conn)
    return str(Settings.CACHE_DB_PATH)


def sync_account_manager_sqlite_store() -> str:
    return ensure_account_manager_sqlite_store()
