"""Unified SQLite bootstrap for the local main database."""
from __future__ import annotations

from typing import Callable

import settings as Settings
from tools.data.hub import DataHub
from tools.data.sqlite import data_source as data_source_sqlite
from tools.data.sqlite import factor_metadata as factor_metadata_sqlite
from tools.data.sqlite import factor_source_settings as factor_source_settings_sqlite
from tools.data.sqlite import factor_source_store as factor_source_store_sqlite
from tools.data.sqlite import factor_source_workspace_settings as factor_source_workspace_settings_sqlite
from tools.data.sqlite import account_manager as account_manager_sqlite


def _call(func: Callable[[], str]) -> str:
    return func()


def ensure_unified_sqlite_store() -> str:
    """Ensure all unified-local SQLite mirrors are materialized."""
    _call(data_source_sqlite.ensure_data_source_sqlite_store)
    _call(account_manager_sqlite.ensure_account_manager_sqlite_store)
    _call(factor_metadata_sqlite.ensure_factor_metadata_sqlite_store)
    _call(factor_source_store_sqlite.ensure_factor_source_sqlite_store)
    _call(factor_source_settings_sqlite.ensure_factor_source_settings_sqlite_store)
    _call(factor_source_workspace_settings_sqlite.ensure_factor_source_workspace_settings_sqlite_store)
    DataHub.get_instance().ensure_visits_schema()
    Settings.CACHE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return str(Settings.CACHE_DB_PATH)
