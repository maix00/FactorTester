"""OpenCTP 品种列表同步模块。"""

from tools.data.hub import DataHub

from ._store import (
    SOURCE_KEY,
    SOURCE_LABEL,
    TABLE_NAME,
    sync_products_from_openctp,
    load_products_list,
)

DataHub.get_instance().register_visit_source(SOURCE_KEY, SOURCE_LABEL)

__all__ = [
    "sync_products_from_openctp",
    "load_products_list",
]
