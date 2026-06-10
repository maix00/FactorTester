"""Central registry for source-module imports."""
from __future__ import annotations

from importlib import import_module
from typing import Iterable


_SOURCE_MODULES: list[str] = [
    "sources.LocalCNFutures.CNFutures",
]


def register_source_module(module_name: str) -> None:
    """Register a source module that should be imported on startup."""
    if module_name not in _SOURCE_MODULES:
        _SOURCE_MODULES.append(module_name)


def iter_source_modules() -> tuple[str, ...]:
    return tuple(_SOURCE_MODULES)


def load_all_sources() -> tuple[str, ...]:
    """Import all registered source modules once."""
    loaded: list[str] = []
    for module_name in _SOURCE_MODULES:
        import_module(module_name)
        loaded.append(module_name)
    return tuple(loaded)
