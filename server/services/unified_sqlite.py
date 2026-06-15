"""Unified SQLite bootstrap for the local main database."""
from __future__ import annotations

from typing import Callable

import Settings


def _call(func: Callable[[], str]) -> str:
    return func()


def ensure_unified_sqlite_store() -> str:
    """Ensure all unified-local SQLite mirrors are materialized."""
    from server.services.data_dictionary_sqlite import ensure_data_dictionary_sqlite_store
    from server.services.data_source_sqlite import ensure_data_source_sqlite_store
    from server.services.factor_metadata_sqlite import ensure_factor_metadata_sqlite_store
    from server.services.user_sqlite import ensure_user_sqlite_store
    from tools.data.hub import DataHub

    _call(ensure_data_source_sqlite_store)
    _call(ensure_user_sqlite_store)
    _call(ensure_factor_metadata_sqlite_store)
    _call(ensure_data_dictionary_sqlite_store)
    DataHub.get_instance().ensure_visits_schema()
    Settings.CACHE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return str(Settings.CACHE_DB_PATH)
