"""Short-lived host LAN snapshots consumed by containerized Manager."""

from __future__ import annotations

import ipaddress
import json
import os
import time
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlparse

from server.manager.network_endpoints import (
    ServerEndpoints,
    client_endpoint_for_port,
)


LAN_ADDRESS_STATE_FILE_ENV = "FACTORTESTER_LAN_ADDRESS_STATE_FILE"
LAN_ADDRESS_MAX_AGE_ENV = "FACTORTESTER_LAN_ADDRESS_MAX_AGE_SECONDS"
DEFAULT_LAN_ADDRESS_MAX_AGE_SECONDS = 20.0


def usable_lan_address(value: object) -> str | None:
    """Return a displayable IP, excluding local-only values."""
    raw = str(value or "").strip()
    try:
        address = ipaddress.ip_address(raw)
    except ValueError:
        return None
    if (
        address.is_loopback
        or address.is_unspecified
        or address.is_link_local
        or address.is_multicast
    ):
        return None
    return address.compressed


def current_host_lan_addresses(*, now: float | None = None) -> list[str] | None:
    """Read a fresh host snapshot, or return ``None`` when not configured."""
    snapshot_path = str(os.environ.get(LAN_ADDRESS_STATE_FILE_ENV) or "").strip()
    if not snapshot_path:
        return None
    try:
        max_age = max(
            1.0,
            float(
                os.environ.get(LAN_ADDRESS_MAX_AGE_ENV)
                or DEFAULT_LAN_ADDRESS_MAX_AGE_SECONDS
            ),
        )
        payload = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
        observed_at = float(payload.get("observed_at") or 0)
        current = time.time() if now is None else float(now)
        values = payload.get("addresses")
        if (
            int(payload.get("schema_version") or 0) != 1
            or not isinstance(values, list)
            or current - observed_at > max_age
            or observed_at > current + 5.0
        ):
            return []
        return sorted({
            address for value in values
            if (address := usable_lan_address(value)) is not None
        })
    except (OSError, TypeError, ValueError):
        return []


def dynamic_host_client_endpoints(
    current: ServerEndpoints | None,
) -> ServerEndpoints | None:
    """Derive current 7998/7997 client endpoints from a fresh snapshot."""
    addresses = current_host_lan_addresses()
    if addresses is None or current is None:
        return None
    if not addresses:
        raise ValueError("current host LAN address is unavailable")
    control = urlparse(current.client_control_endpoint)
    host = addresses[0]
    rendered = f"[{host}]" if ":" in host else host
    selected_control = (
        f"{control.scheme or 'http'}://{rendered}:{control.port or 7998}"
    )
    selected_data = client_endpoint_for_port(
        selected_control,
        urlparse(current.client_data_endpoint).port or 7997,
        name="host LAN transfer data endpoint",
    )
    return replace(
        current,
        client_control_endpoint=selected_control,
        client_data_endpoint=selected_data,
    )
