"""Installed JSON metadata discovery, followed by explicit runtime activation."""
from __future__ import annotations

from importlib import import_module
import os
from pathlib import Path
from threading import RLock

from traderesearch_data.bundles import BundleManifest, discover_bundle_manifests

BUNDLE_ROOT = Path(os.environ.get("TR_SOURCE_BUNDLE_ROOT", Path(__file__).parent))
_INVENTORY: tuple[BundleManifest, ...] | None = None
_MODULES: tuple[str, ...] = ()
_LOCK = RLock()


def installed_bundles(*, refresh: bool = False) -> tuple[BundleManifest, ...]:
    """Reuse a source-free snapshot; installation refresh validates atomically."""
    global _INVENTORY, _MODULES
    if not refresh and _INVENTORY is not None:
        return _INVENTORY
    with _LOCK:
        if refresh or _INVENTORY is None:
            inventory = discover_bundle_manifests(BUNDLE_ROOT)
            modules = tuple(dict.fromkeys(module for bundle in inventory
                                          if bundle.execution_location == "server"
                                          for module in bundle.entrypoints))
            _MODULES = modules
            _INVENTORY = inventory
        return _INVENTORY


def iter_source_modules() -> tuple[str, ...]:
    installed_bundles()
    return _MODULES


def load_all_sources() -> tuple[str, ...]:
    """Activate trusted server-installed plugins, never client manifests.

    This preserves existing source registration/loading. Catalog discovery
    itself is available separately through installed_bundles without activation.
    """
    modules = iter_source_modules()
    for module_name in modules:
        module = import_module(module_name)
        register = getattr(module, "register_source_declarations", None)
        if callable(register):
            register()
    return modules
