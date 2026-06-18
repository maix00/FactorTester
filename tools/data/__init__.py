"""工具层 — data 子包。"""

FACTOR_WORKSPACE = True

if FACTOR_WORKSPACE:
    from . import types
    from .views import ProductDataView

__all__ = [
    "ProductDataView",
    "types",
]
