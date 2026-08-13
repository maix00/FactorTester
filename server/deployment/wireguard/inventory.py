"""Strict public metadata model for FactorTester WireGuard membership."""

from __future__ import annotations

import base64
import ipaddress
import re
from dataclasses import dataclass


INVENTORY_SCHEMA_VERSION = 1
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")
_NODE_FIELDS = {
    "server_id",
    "interface_address",
    "public_key",
    "endpoint",
    "listen_port",
    "gateway",
    "gateway_server_id",
}


def _identifier(value: object, *, field: str) -> str:
    selected = str(value or "").strip()
    if not _IDENTIFIER.fullmatch(selected):
        raise ValueError(f"{field} must be a stable lowercase identifier")
    return selected


def _wireguard_key(value: object, *, field: str) -> str:
    selected = str(value or "").strip()
    try:
        decoded = base64.b64decode(selected, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{field} must be a WireGuard base64 key") from exc
    if len(decoded) != 32:
        raise ValueError(f"{field} must decode to 32 bytes")
    return selected


def _port(value: object, *, field: str, required: bool = False) -> int | None:
    if value in {None, ""}:
        if required:
            raise ValueError(f"{field} is required")
        return None
    try:
        selected = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc
    if not 1 <= selected <= 65535:
        raise ValueError(f"{field} must be between 1 and 65535")
    return selected


def _endpoint(value: object, *, required: bool) -> str:
    selected = str(value or "").strip()
    if not selected:
        if required:
            raise ValueError("gateway endpoint is required")
        return ""
    if any(character.isspace() for character in selected) or "/" in selected:
        raise ValueError("endpoint must be host:port")
    if selected.startswith("["):
        closing = selected.find("]")
        if closing <= 1 or closing + 1 >= len(selected) or selected[closing + 1] != ":":
            raise ValueError("endpoint must be host:port")
        host = selected[1:closing]
        raw_port = selected[closing + 2:]
        try:
            ipaddress.IPv6Address(host)
        except ValueError as exc:
            raise ValueError("endpoint has an invalid IPv6 host") from exc
    else:
        host, separator, raw_port = selected.rpartition(":")
        if not separator or not host or ":" in host:
            raise ValueError("endpoint must be host:port")
    _port(raw_port, field="endpoint port", required=True)
    return selected


def _endpoint_port(value: str) -> int:
    raw_port = value.rsplit(":", 1)[1]
    return int(raw_port)


def _reject_private_material(value: object, *, path: str = "inventory") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower().replace("-", "_")
            if "private" in lowered and "key" in lowered:
                raise ValueError(f"{path} must not contain private key material")
            _reject_private_material(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_private_material(item, path=f"{path}[{index}]")


@dataclass(frozen=True, slots=True)
class TunnelNode:
    server_id: str
    interface_address: str
    public_key: str
    endpoint: str = ""
    listen_port: int | None = None
    gateway: bool = False
    gateway_server_id: str = ""

    @property
    def address(self) -> ipaddress.IPv4Interface | ipaddress.IPv6Interface:
        return ipaddress.ip_interface(self.interface_address)

    @property
    def host_route(self) -> str:
        return f"{self.address.ip}/{self.address.max_prefixlen}"


@dataclass(frozen=True, slots=True)
class TunnelSpec:
    name: str
    cidr: str
    nodes: tuple[TunnelNode, ...]

    @property
    def network(self) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
        return ipaddress.ip_network(self.cidr)

    def node(self, server_id: str) -> TunnelNode:
        selected = str(server_id or "").strip()
        for node in self.nodes:
            if node.server_id == selected:
                return node
        raise KeyError(f"server {selected or '<empty>'} has no {self.name} identity")


@dataclass(frozen=True, slots=True)
class WireGuardInventory:
    cluster_id: str
    generation: int
    tunnels: tuple[TunnelSpec, ...]

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "WireGuardInventory":
        if not isinstance(value, dict):
            raise ValueError("WireGuard inventory must be an object")
        _reject_private_material(value)
        if value.get("schema_version") != INVENTORY_SCHEMA_VERSION:
            raise ValueError("unsupported WireGuard inventory schema")
        cluster_id = _identifier(value.get("cluster_id"), field="cluster_id")
        try:
            generation = int(value.get("generation") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("generation must be an integer") from exc
        if generation < 1:
            raise ValueError("generation must be positive")
        raw_tunnels = value.get("tunnels")
        if not isinstance(raw_tunnels, dict) or not raw_tunnels:
            raise ValueError("tunnels must be a non-empty object")
        tunnels = tuple(
            _tunnel(name, raw)
            for name, raw in sorted(raw_tunnels.items())
        )
        public_keys = [
            node.public_key for tunnel in tunnels for node in tunnel.nodes
        ]
        if len(public_keys) != len(set(public_keys)):
            raise ValueError("every tunnel identity must use a distinct public key")
        return cls(cluster_id=cluster_id, generation=generation, tunnels=tunnels)

    def tunnel(self, name: str) -> TunnelSpec:
        selected = str(name or "").strip()
        for tunnel in self.tunnels:
            if tunnel.name == selected:
                return tunnel
        raise KeyError(f"unknown WireGuard tunnel: {selected or '<empty>'}")


def _tunnel(name: object, value: object) -> TunnelSpec:
    tunnel_name = _identifier(name, field="tunnel name")
    if not isinstance(value, dict):
        raise ValueError(f"tunnel {tunnel_name} must be an object")
    unknown = set(value) - {"cidr", "nodes"}
    if unknown:
        raise ValueError(f"tunnel {tunnel_name} has unknown fields: {', '.join(sorted(unknown))}")
    try:
        network = ipaddress.ip_network(str(value.get("cidr") or ""), strict=True)
    except ValueError as exc:
        raise ValueError(f"tunnel {tunnel_name} has an invalid cidr") from exc
    raw_nodes = value.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise ValueError(f"tunnel {tunnel_name} nodes must be a non-empty list")
    nodes = tuple(_node(item, network=network) for item in raw_nodes)
    identifiers = [node.server_id for node in nodes]
    addresses = [node.address.ip for node in nodes]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError(f"tunnel {tunnel_name} server_id values must be unique")
    if len(addresses) != len(set(addresses)):
        raise ValueError(f"tunnel {tunnel_name} addresses must be unique")
    by_id = {node.server_id: node for node in nodes}
    gateways = {node.server_id for node in nodes if node.gateway}
    if not gateways:
        raise ValueError(f"tunnel {tunnel_name} requires at least one gateway")
    for node in nodes:
        if node.gateway:
            if node.gateway_server_id:
                raise ValueError("a gateway cannot declare gateway_server_id")
            continue
        gateway = by_id.get(node.gateway_server_id)
        if gateway is None or not gateway.gateway:
            raise ValueError(
                f"node {node.server_id} must reference an enabled tunnel gateway"
            )
    return TunnelSpec(name=tunnel_name, cidr=str(network), nodes=nodes)


def _node(
    value: object,
    *,
    network: ipaddress.IPv4Network | ipaddress.IPv6Network,
) -> TunnelNode:
    if not isinstance(value, dict):
        raise ValueError("each tunnel node must be an object")
    unknown = set(value) - _NODE_FIELDS
    if unknown:
        raise ValueError(f"tunnel node has unknown fields: {', '.join(sorted(unknown))}")
    server_id = _identifier(value.get("server_id"), field="server_id")
    try:
        interface = ipaddress.ip_interface(
            str(value.get("interface_address") or ""),
        )
    except ValueError as exc:
        raise ValueError(f"node {server_id} has an invalid interface_address") from exc
    if interface.ip not in network or interface.version != network.version:
        raise ValueError(f"node {server_id} address is outside the tunnel cidr")
    gateway = bool(value.get("gateway", False))
    endpoint = _endpoint(value.get("endpoint"), required=gateway)
    listen_port = _port(
        value.get("listen_port"),
        field="listen_port",
        required=gateway,
    )
    if gateway and _endpoint_port(endpoint) != listen_port:
        raise ValueError("gateway endpoint port must match listen_port")
    return TunnelNode(
        server_id=server_id,
        interface_address=str(interface),
        public_key=_wireguard_key(
            value.get("public_key"), field=f"node {server_id} public_key",
        ),
        endpoint=endpoint,
        listen_port=listen_port,
        gateway=gateway,
        gateway_server_id=str(value.get("gateway_server_id") or "").strip(),
    )
