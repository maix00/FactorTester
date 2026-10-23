"""Truthful per-service NautilusTrader capability projection."""

from __future__ import annotations

from importlib import metadata


def native_capabilities() -> dict[str, object]:
    """Describe installed library support without claiming venue connectivity.

    An installed engine is not a configured data feed or execution adapter.
    In particular, the live mode must stay unavailable until an explicit
    broker/venue adapter and its reconciliation contract are installed.
    """
    try:
        version = metadata.version("nautilus_trader")
    except metadata.PackageNotFoundError:
        version = None
    return {
        "engine": "nautilus_trader",
        "engine_version": version,
        "installed": version is not None,
        "backtest_reports": version is not None,
        "sandbox": {"available": False, "reason": "live data adapter not configured"},
        "live": {"available": False, "reason": "venue execution adapter not configured"},
    }
