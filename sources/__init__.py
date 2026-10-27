"""Data-source metadata discovery and explicit runtime activation."""
from .registry import installed_bundles, iter_source_modules, load_all_sources

__all__ = ["installed_bundles", "iter_source_modules", "load_all_sources"]
