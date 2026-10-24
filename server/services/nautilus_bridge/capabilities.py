"""Truthful per-service NautilusTrader capability projection."""

from __future__ import annotations

from importlib import metadata
from typing import Any

from server.services.nautilus_bridge.native_configuration import native_configuration_schema


def market_data_source_capabilities() -> dict[str, Any]:
    """Return source declarations and exact adapter admissions without file probes."""
    from server.services.nautilus_bridge.source_registry import from_server_sources

    rows = []
    for item in from_server_sources().capabilities():
        rows.append({
            "family_key": item.family_key,
            "member_key": item.member_key,
            "frequency": item.frequency,
            "sampling_mode": item.sampling_mode,
            "data_kind": item.data_kind,
            "market_depth": item.market_depth,
            "delivery_mode": item.delivery_mode,
            "mode_available": item.mode_available,
            "timezone": item.timezone,
            "layout": item.layout,
            "naming_scheme": item.naming_scheme,
            "time_columns": dict(item.time_columns),
            "data_columns": dict(item.data_columns),
            "instrument_scope": item.instrument_scope,
            "bar_time_semantics": item.bar_time_semantics,
            "raw_timestamp_unit": item.raw_timestamp_unit,
            "adapter_id": item.adapter_id,
            "adapter_available": item.adapter_id is not None,
            "supported_book_types": list(item.supported_book_types),
            "reason": item.reason,
        })
    return {"available": True, "members": rows}


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
    schema = native_configuration_schema()
    schema["available"] = version == schema["native_version"]
    if not schema["available"]:
        schema["reason"] = (
            "Nautilus configuration controls are pinned to "
            f"{schema['native_version']}; installed package is {version or 'missing'}."
        )
    try:
        market_data_sources = market_data_source_capabilities()
    except Exception as exc:
        # Keep the venue schema available if an optional source declaration
        # cannot be imported, but never claim that its adapters are supported.
        market_data_sources = {
            "available": False,
            "members": [],
            "reason": f"market data source declarations unavailable: {type(exc).__name__}",
        }
    return {
        "engine": "nautilus_trader",
        "engine_version": version,
        "installed": version is not None,
        "backtest_reports": version is not None,
        "simulated_venue_config": schema,
        "market_data_sources": market_data_sources,
        "sandbox": {"available": False, "reason": "live data adapter not configured"},
        "live": {"available": False, "reason": "venue execution adapter not configured"},
    }
