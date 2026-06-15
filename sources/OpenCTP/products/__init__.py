"""OpenCTP 品种列表同步模块。"""

from sources.visits import register_visit_source

from ._store import (
    SOURCE_KEY,
    SOURCE_LABEL,
    TABLE_NAME,
    sync_products_from_openctp,
    load_products_list,
)

register_visit_source(SOURCE_KEY, SOURCE_LABEL)

__all__ = [
    "sync_products_from_openctp",
    "load_products_list",
]
