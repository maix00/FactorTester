"""Products CLI module."""

from .controller import product_group_selection, products
from .categories import product_categories
from .catalog import product_catalog
from .data_sources import product_sources

products.add_command(product_categories)
products.add_command(product_catalog)
products.add_command(product_sources)

__all__ = [
    "product_categories",
    "product_catalog",
    "product_group_selection",
    "product_sources",
    "products",
]
