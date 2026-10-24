"""Central registry for source-module imports."""
from __future__ import annotations

from importlib import import_module
from typing import Iterable


_SOURCE_MODULES: list[str] = [
    "sources.Local.data_source_bundle",
    "sources.LocalCNFutures.CNFutures",
    "sources.LocalCNFutures.artifacts",
]


def register_source_module(module_name: str) -> None:
    """Register a source module that should be imported on startup."""
    if module_name not in _SOURCE_MODULES:
        _SOURCE_MODULES.append(module_name)


def iter_source_modules() -> tuple[str, ...]:
    return tuple(_SOURCE_MODULES)


def load_all_sources() -> tuple[str, ...]:
    """Import source modules and register definitions without listing products."""
    loaded: list[str] = []
    for module_name in _SOURCE_MODULES:
        module = import_module(module_name)
        register = getattr(module, "register_source_declarations", None)
        if callable(register):
            register()
        loaded.append(module_name)
    return tuple(loaded)
