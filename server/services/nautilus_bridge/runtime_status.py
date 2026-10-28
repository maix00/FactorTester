"""Report the runtime NautilusTrader version without importing it."""

from __future__ import annotations

from importlib import metadata, util

from server.services.nautilus_bridge.version import NAUTILUS_VERSION


def nautilus_runtime_status() -> dict:
    available = util.find_spec("nautilus_trader") is not None
    version = ""
    if available:
        try:
            version = metadata.version("nautilus_trader")
        except metadata.PackageNotFoundError:
            version = "unknown"
    return {
        "available": available,
        "version": version,
        "expected": NAUTILUS_VERSION,
        "compatible": available and version == NAUTILUS_VERSION,
    }
