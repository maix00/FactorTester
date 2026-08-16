"""Products CLI module."""

from .controller import product_group_selection, products
from .categories import product_categories

products.add_command(product_categories)

__all__ = ["product_categories", "product_group_selection", "products"]
