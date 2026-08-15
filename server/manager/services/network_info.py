"""Server-provided network addresses and public-node projections.

The Web and Swift clients only render this projection.  They do not infer a
public address from their own connection, and a public address is never put
in the LAN-address list by the client.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from typing import Any, Iterable
from urllib.parse import urlparse

from server.manager.domain.organization_scope import (
    configured_managed_organizations,
)


LAN_ADDRESSES_ENV = "FACTORTESTER_LAN_ADDRESSES"
MAX_PUBLIC_SERVER_TARGETS = 3


def _usable_lan_address(value: object) -> str | None:
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


def endpoint_host(endpoint: object) -> str:
    """Return the host portion only; ports are a separate protocol detail."""
    try:
        return str(urlparse(str(endpoint or "")).hostname or "")
    except ValueError:
        return ""


def local_internal_addresses(
    *,
    hostnames: Iterable[str] | None = None,
    configured: Iterable[str] | None = None,
) -> list[str]:
    """Return addresses that another LAN device can use for this Manager.

    A deployment should set ``FACTORTESTER_LAN_ADDRESSES`` behind Docker;
    automatic hostname lookup is kept for local development and tests.
    """
    explicit = configured
    if explicit is None:
        raw_configured = os.environ.get(LAN_ADDRESSES_ENV)
        if raw_configured is not None:
            explicit = raw_configured.split(",")
    if explicit is not None:
        return sorted({
            address for value in explicit
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


def _sort_target(item: dict[str, object]) -> tuple[float, float, str]:
    latency = item.get("latency_ms")
    return (
        float(latency) if latency is not None else float("inf"),
        float(item.get("load") or 0.0),
        str(item.get("server_id") or ""),
    )


def _public_server_flag(item: dict[str, object]) -> bool:
    # Main was the historical public role.  New registrations send the
    # explicit flag, while old registry files remain readable.
    return bool(item.get("public_server", item.get("role") == "main"))


def _managed_organizations(item: dict[str, object]) -> list[str]:
    values = item.get("managed_organizations") or []
    if isinstance(values, str):
        values = values.split(",")
    if isinstance(values, (list, tuple, set)):
        result = sorted({
            str(value).strip()
            for value in values
            if str(value).strip()
        })
        if result:
            return result
    # Registrations written before organization scope was added are still
    # valid online peers.  Their role is enough to apply the deployment
    # default without making the client guess an institution.
    return list(configured_managed_organizations(
        public_server=_public_server_flag(item),
        server_role=str(item.get("role") or "feat"),
    ))


def _target_from_registration(
    item: dict[str, object],
    *,
    endpoint: str,
    latency_ms: float | None = None,
    load: float = 0.0,
    active_jobs: int = 0,
    queue_depth: int = 0,
) -> dict[str, object] | None:
    host = endpoint_host(endpoint)
    if not host:
        return None
    return {
        "server_id": str(item.get("server_id") or ""),
        "role": str(item.get("role") or ""),
        "endpoint": endpoint.rstrip("/"),
        "public_address": host,
        "public_server": True,
        "online": True,
        "latency_ms": latency_ms,
        "load": max(0.0, float(load or 0.0)),
        "active_jobs": max(0, int(active_jobs or 0)),
        "queue_depth": max(0, int(queue_depth or 0)),
        "revision": str(item.get("revision") or ""),
    }


def public_manager_targets(
    registry: Any,
    *,
    source_server_id: str,
) -> list[dict[str, object]]:
    """Return online public HTTPS peers ordered by latency and load."""
    candidates: list[dict[str, object]] = []
    for item in registry.servers(include_offline=False):
        server_id = str(item.get("server_id") or "").strip()
        endpoint = str(item.get("endpoint") or "").strip().rstrip("/")
        if (
            not server_id
            or server_id == source_server_id
            or not endpoint
            or not _public_server_flag(item)
        ):
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
        load = item.get("load") if isinstance(item.get("load"), dict) else {}
        try:
            latency = max(0.0, float(item.get("latency_ms")))
        except (TypeError, ValueError):
            latency = None
        try:
            load_value = max(0.0, float(load.get("load") or 0.0))
            active_jobs = max(0, int(load.get("active_jobs") or 0))
            queue_depth = max(0, int(load.get("queue_depth") or 0))
        except (TypeError, ValueError):
            load_value, active_jobs, queue_depth = 0.0, 0, 0
        target = _target_from_registration(
            item,
            endpoint=endpoint,
            latency_ms=latency,
            load=load_value,
            active_jobs=active_jobs,
            queue_depth=queue_depth,
        )
        if target is not None:
            candidates.append(target)
    return sorted(candidates, key=_sort_target)


def _public_server_targets(
    registry: Any,
    *,
    source_server_id: str,
    public_server: bool,
    current_endpoint: str,
    limit: int | None = MAX_PUBLIC_SERVER_TARGETS,
) -> list[dict[str, object]]:
    """Include this Manager when public and optionally cap the result."""
    targets = public_manager_targets(
        registry, source_server_id=source_server_id,
    )
    if public_server:
        current = _target_from_registration(
            {"server_id": source_server_id, "role": "main"},
            endpoint=current_endpoint,
            latency_ms=0.0,
        )
        if current is not None:
            targets.append(current)
    ordered = sorted(targets, key=_sort_target)
    return ordered if limit is None else ordered[:limit]


def _internal_server_addresses(
    registry: Any,
    *,
    source_server_id: str,
    public_server: bool,
) -> list[str]:
    """Return online private addresses from the current and peer LAN nodes."""
    values: set[str] = set()
    if not public_server:
        values.update(local_internal_addresses())
    for item in registry.servers(include_offline=False):
        if (
            str(item.get("server_id") or "") == source_server_id
            or _public_server_flag(item)
        ):
            continue
        raw_values = item.get("internal_addresses") or []
        if isinstance(raw_values, str):
            raw_values = raw_values.split(",")
        if not isinstance(raw_values, (list, tuple, set)):
            continue
        values.update(
            address for value in raw_values
            if (address := _usable_lan_address(value)) is not None
            and ipaddress.ip_address(address).is_private
        )
    return sorted(values)


def _internal_server_targets(
    registry: Any,
    *,
    source_server_id: str,
    server_role: str,
    public_server: bool,
    managed_organizations: Iterable[str],
) -> list[dict[str, object]]:
    """Return online internal nodes with their organization scope."""
    targets: list[dict[str, object]] = []

    def append_target(
        *,
        server_id: str,
        role: str,
        addresses: object,
        organizations: Iterable[str],
    ) -> None:
        if isinstance(addresses, str):
            addresses = addresses.split(",")
        if not isinstance(addresses, (list, tuple, set)):
            return
        values = sorted({
            address
            for value in addresses
            if (address := _usable_lan_address(value)) is not None
            and ipaddress.ip_address(address).is_private
        })
        if not values:
            return
        targets.append({
            "server_id": server_id,
            "role": role,
            "addresses": values,
            "manager_port": 7998,
            "managed_organizations": sorted({
                str(value).strip()
                for value in organizations
                if str(value).strip()
            }),
            "online": True,
        })

    if not public_server:
        append_target(
            server_id=source_server_id,
            role=server_role,
            addresses=local_internal_addresses(),
            organizations=managed_organizations,
        )
    for item in registry.servers(include_offline=False):
        server_id = str(item.get("server_id") or "").strip()
        if (
            not server_id
            or server_id == source_server_id
            or _public_server_flag(item)
        ):
            continue
        append_target(
            server_id=server_id,
            role=str(item.get("role") or ""),
            addresses=item.get("internal_addresses") or [],
            organizations=_managed_organizations(item),
        )
    return sorted(targets, key=lambda item: str(item.get("server_id") or ""))


def server_network_info(
    *,
    registry: Any,
    federation_config: dict[str, object],
    source_server_id: str,
    server_role: str,
    public_server: bool,
    request_endpoint: str = "",
    manager_public_endpoint: str = "",
    managed_organizations: Iterable[str] = (),
) -> dict[str, object]:
    """Build the server-provided network information shown by clients."""
    local_scope = tuple(managed_organizations) or configured_managed_organizations(
        public_server=public_server,
        server_role=server_role,
    )
    configured_endpoint = str(
        manager_public_endpoint
        or federation_config.get("public_endpoint")
        or ""
    ).strip().rstrip("/")
    advertised_endpoint = configured_endpoint
    if public_server and not advertised_endpoint and request_endpoint:
        # Compatibility fallback for a directly constructed Manager in tests;
        # deployed instances set FACTORTESTER_MANAGER_PUBLIC_ENDPOINT.
        advertised_endpoint = str(request_endpoint).strip().rstrip("/")
    peer_targets = public_manager_targets(
        registry, source_server_id=source_server_id,
    )
    online_public_targets = _public_server_targets(
        registry,
        source_server_id=source_server_id,
        public_server=public_server,
        current_endpoint=advertised_endpoint,
        limit=None,
    )
    public_targets = online_public_targets[:MAX_PUBLIC_SERVER_TARGETS]
    internal_addresses = _internal_server_addresses(
        registry,
        source_server_id=source_server_id,
        public_server=public_server,
    )
    internal_targets = _internal_server_targets(
        registry,
        source_server_id=source_server_id,
        server_role=server_role,
        public_server=public_server,
        managed_organizations=local_scope,
    )
    public_addresses = list(dict.fromkeys(
        str(item.get("public_address") or "")
        for item in public_targets
        if str(item.get("public_address") or "")
    ))
    return {
        "server_id": source_server_id,
        "role": server_role,
        "internal_addresses": internal_addresses,
        "internal_server_addresses": internal_addresses,
        "manager_port": 7998,
        "public_server": public_server,
        "advertised_public_endpoint": advertised_endpoint,
        "current_public_target": peer_targets[0] if peer_targets else None,
        # Backward-compatible peer-only field used by Swift target switching.
        "public_targets": peer_targets,
        "public_server_targets": public_targets,
        "public_server_addresses": public_addresses,
        "online_public_server_targets": online_public_targets,
        "online_public_server_addresses": list(dict.fromkeys(
            str(item.get("public_address") or "")
            for item in online_public_targets
            if str(item.get("public_address") or "")
        )),
        "internal_server_targets": internal_targets,
        "source": "manager",
    }
