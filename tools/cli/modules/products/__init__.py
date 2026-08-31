"""Products CLI module."""

from .catalog import product_catalog
from .categories import product_categories
from .controller import product_library
from .data_sources import product_sources
from .groups import product_group_selection, product_groups

product_library.add_command(product_categories)
product_library.add_command(product_catalog)
product_library.add_command(product_sources)
product_library.add_command(product_groups)

__all__ = [
    "product_categories",
    "product_catalog",
    "product_group_selection",
    "product_sources",
    "product_library",
]
