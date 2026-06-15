"""OpenCTP 品种列表同步模块。"""

from tools.data.hub import DataHub

from ._store import (
    SOURCE_KEY,
    SOURCE_LABEL,
    RAW_TABLE_NAME,
    SOURCE_VIEW_NAME,
    ensure_sqlite_store,
    sync_products_from_openctp,
    load_products_list,
)

DataHub.get_instance().register_visit_source(SOURCE_KEY, SOURCE_LABEL)
ensure_sqlite_store()

__all__ = [
    "SOURCE_KEY",
    "SOURCE_LABEL",
    "RAW_TABLE_NAME",
    "SOURCE_VIEW_NAME",
    "ensure_sqlite_store",
    "sync_products_from_openctp",
    "load_products_list",
]
