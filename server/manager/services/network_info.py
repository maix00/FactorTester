"""Network discovery and public Manager target selection.

This module owns the small, deterministic projection that clients use to
display server addresses and choose a public Manager.  The client never
derives or embeds a public IP; the active Manager supplies the projection
from its federation registry and configuration.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from typing import Any, Iterable
from urllib.parse import urlparse


LAN_ADDRESSES_ENV = "FACTORTESTER_LAN_ADDRESSES"


def _usable_lan_address(value: object) -> str | None:
    """Return a displayable IPv4 LAN address, excluding local-only values."""
    raw = str(value or "").strip()
    try:
        address = ipaddress.ip_address(raw)
    except ValueError:
        return None
    if not isinstance(address, ipaddress.IPv4Address):
        return None
    if (
        address.is_loopback
        or address.is_unspecified
        or address.is_link_local
        or address.is_multicast
    ):
        return None
    return str(address)


def public_manager_targets(
    registry: Any,
    *,
    source_server_id: str,
) -> list[dict[str, object]]:
    """Return online HTTPS peers ordered by latency, load, then identity."""
    candidates: list[dict[str, object]] = []
    for item in registry.servers(include_offline=False):
        server_id = str(item.get("server_id") or "").strip()
        endpoint = str(item.get("endpoint") or "").strip().rstrip("/")
        if not server_id or server_id == source_server_id or not endpoint:
            continue
        parsed = urlparse(endpoint)
        if (
            parsed.scheme.lower() != "https"
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            continue
        raw_load = item.get("load")
        load = raw_load if isinstance(raw_load, dict) else {}
        try:
            latency = max(0.0, float(item.get("latency_ms")))
        except (TypeError, ValueError):
            latency = None
        try:
            load_value = max(0.0, float(load.get("load") or 0.0))
        except (TypeError, ValueError):
            load_value = 0.0
        candidates.append({
            "server_id": server_id,
            "role": str(item.get("role") or ""),
            "endpoint": endpoint,
            "online": True,
            "latency_ms": latency,
            "load": load_value,
            "active_jobs": int(load.get("active_jobs") or 0),
            "queue_depth": int(load.get("queue_depth") or 0),
            "revision": str(item.get("revision") or ""),
        })
    return sorted(
        candidates,
        key=lambda item: (
            float(item["latency_ms"])
            if item.get("latency_ms") is not None else float("inf"),
            float(item.get("load") or 0.0),
            str(item.get("server_id") or ""),
        ),
    )


def local_internal_addresses(
    *,
    hostnames: Iterable[str] | None = None,
    configured: Iterable[str] | None = None,
) -> list[str]:
    """Return addresses that another LAN device can use for this Manager.

    A deployment can provide ``FACTORTESTER_LAN_ADDRESSES`` as a comma-separated
    authoritative list. This is required behind container networking, where
    automatic discovery sees a Docker bridge address instead of the host LAN.
    ``hostnames`` and ``configured`` are injectable for deterministic tests.
    """
    explicit = configured
    if explicit is None:
        raw_configured = os.environ.get(LAN_ADDRESSES_ENV)
        if raw_configured is not None:
            explicit = raw_configured.split(",")
    if explicit is not None:
        return sorted({
            address
            for value in explicit
            if (address := _usable_lan_address(value)) is not None
        })

    values: set[str] = set()
    names = (
        set(hostnames)
        if hostnames is not None
        else {socket.gethostname(), socket.getfqdn()}
    )
    for name in names:
        if not name:
            continue
        try:
            infos = socket.getaddrinfo(name, None, socket.AF_INET)
        except OSError:
            continue
        for info in infos:
            address = _usable_lan_address(info[4][0])
            if address is not None:
                values.add(address)
    return sorted(values)


def server_network_info(
    *,
    registry: Any,
    federation_config: dict[str, object],
    source_server_id: str,
    server_role: str,
    public_server: bool,
    request_endpoint: str = "",
) -> dict[str, object]:
    """Build the server-provided network information shown by clients."""
    configured_endpoint = str(
        federation_config.get("public_endpoint") or ""
    ).strip().rstrip("/")
    advertised_endpoint = configured_endpoint
    if public_server and request_endpoint:
        advertised_endpoint = str(request_endpoint).strip().rstrip("/")
    targets = public_manager_targets(
        registry,
        source_server_id=source_server_id,
    )
    return {
        "server_id": source_server_id,
        "role": server_role,
        "internal_addresses": local_internal_addresses(),
        "manager_port": 7998,
        "public_server": public_server,
        "advertised_public_endpoint": advertised_endpoint,
        "current_public_target": targets[0] if targets else None,
        "public_targets": targets,
        "source": "manager",
    }
