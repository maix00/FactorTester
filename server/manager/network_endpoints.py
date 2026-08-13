"""Validated public and WireGuard endpoint configuration for one node."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlparse

from server.manager.config import PEER_CONTROL_PORT, PEER_DATA_PORT


@dataclass(frozen=True, slots=True)
class ServerEndpoints:
    client_control_endpoint: str
    client_data_endpoint: str
    peer_control_endpoint: str
    peer_data_endpoint: str


def peer_bind_address(value: str) -> str:
    selected = str(value or "").strip()
    if not selected:
        raise ValueError("FactorTester WireGuard bind address is required")
    address = ipaddress.ip_address(selected)
    if address.is_unspecified or address.is_loopback or address.is_multicast:
        raise ValueError("peer listener must bind a private WireGuard address")
    if not address.is_private:
        raise ValueError("peer listener must bind a private WireGuard address")
    return selected


def endpoint_url(host: str, port: int) -> str:
    address = peer_bind_address(host)
    rendered = f"[{address}]" if ":" in address else address
    return f"http://{rendered}:{int(port)}"


def validate_client_endpoint(value: str, *, name: str) -> str:
    selected = str(value or "").strip().rstrip("/")
    parsed = urlparse(selected)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{name} must be an HTTP endpoint")
    if parsed.username or parsed.password:
        raise ValueError(f"{name} must not contain credentials")
    return selected


def validate_peer_endpoint(value: str, *, name: str, port: int) -> str:
    selected = str(value or "").strip().rstrip("/")
    parsed = urlparse(selected)
    if (
        parsed.scheme != "http"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"{name} must be a private WireGuard HTTP endpoint")
    try:
        selected_port = parsed.port
    except ValueError as exc:
        raise ValueError(f"{name} has an invalid port") from exc
    if selected_port != int(port):
        raise ValueError(f"{name} must use port {int(port)}")
    peer_bind_address(parsed.hostname)
    return selected


def validate_server_endpoints(value: ServerEndpoints) -> ServerEndpoints:
    return ServerEndpoints(
        client_control_endpoint=validate_client_endpoint(
            value.client_control_endpoint, name="client control endpoint",
        ),
        client_data_endpoint=validate_client_endpoint(
            value.client_data_endpoint, name="client data endpoint",
        ),
        peer_control_endpoint=validate_peer_endpoint(
            value.peer_control_endpoint,
            name="peer control endpoint",
            port=PEER_CONTROL_PORT,
        ),
        peer_data_endpoint=validate_peer_endpoint(
            value.peer_data_endpoint,
            name="peer data endpoint",
            port=PEER_DATA_PORT,
        ),
    )


def server_endpoints(
    *,
    client_control_endpoint: str,
    client_data_endpoint: str,
    peer_host: str,
    peer_control_port: int = PEER_CONTROL_PORT,
    peer_data_port: int = PEER_DATA_PORT,
) -> ServerEndpoints:
    return validate_server_endpoints(ServerEndpoints(
        client_control_endpoint=validate_client_endpoint(
            client_control_endpoint, name="client control endpoint",
        ),
        client_data_endpoint=validate_client_endpoint(
            client_data_endpoint, name="client data endpoint",
        ),
        peer_control_endpoint=endpoint_url(peer_host, peer_control_port),
        peer_data_endpoint=endpoint_url(peer_host, peer_data_port),
    ))


def endpoints_from_advertisement(value: dict[str, object]) -> ServerEndpoints:
    return validate_server_endpoints(ServerEndpoints(
        client_control_endpoint=str(
            value.get("client_control_endpoint") or ""
        ),
        client_data_endpoint=str(value.get("client_data_endpoint") or ""),
        peer_control_endpoint=str(value.get("peer_control_endpoint") or ""),
        peer_data_endpoint=str(value.get("peer_data_endpoint") or ""),
    ))
