"""Network discovery and public Manager target selection.

This module owns the small, deterministic projection that clients use to
display server addresses and choose a public Manager.  The client never
derives or embeds a public IP; the active Manager supplies the projection
from its federation registry and configuration.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Any, Iterable
from urllib.parse import urlparse


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
) -> list[str]:
    """Discover this host's private/loopback IPv4 addresses.

    ``hostnames`` is injectable so the discovery rule can be tested without
    depending on the machine running the test suite.
    """
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
            address = str(info[4][0] or "").strip()
            try:
                parsed = ipaddress.ip_address(address)
            except ValueError:
                continue
            if parsed.is_private or parsed.is_loopback:
                values.add(address)
    values.add("127.0.0.1")
    return sorted(values, key=lambda value: (value == "127.0.0.1", value))


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
        "advertised_public_endpoint": advertised_endpoint,
        "current_public_target": targets[0] if targets else None,
        "public_targets": targets,
        "source": "manager",
    }
