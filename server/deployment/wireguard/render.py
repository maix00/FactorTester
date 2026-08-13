"""Render one node's owner-only wg-quick configuration from public inventory."""

from __future__ import annotations

from dataclasses import dataclass

from .inventory import TunnelNode, WireGuardInventory, _wireguard_key


@dataclass(frozen=True, slots=True)
class _Peer:
    node: TunnelNode
    allowed_ips: tuple[str, ...]


def render_wireguard_config(
    inventory: WireGuardInventory,
    *,
    server_id: str,
    tunnel: str,
    private_key: str,
) -> str:
    """Return a deterministic config; callers must write it with mode 0600."""
    selected_tunnel = inventory.tunnel(tunnel)
    local = selected_tunnel.node(server_id)
    selected_private_key = _wireguard_key(
        private_key, field="local WireGuard private key",
    )
    lines = [
        "[Interface]",
        f"Address = {local.interface_address}",
        f"PrivateKey = {selected_private_key}",
    ]
    if local.listen_port is not None:
        lines.append(f"ListenPort = {local.listen_port}")
    if local.gateway:
        lines.extend((
            "PostUp = iptables -A FORWARD -i %i -o %i -j ACCEPT",
            "PostDown = iptables -D FORWARD -i %i -o %i -j ACCEPT",
        ))
    for peer in _peers(selected_tunnel.nodes, local=local, cidr=selected_tunnel.cidr):
        lines.extend(("", "[Peer]", f"PublicKey = {peer.node.public_key}"))
        lines.append(f"AllowedIPs = {', '.join(peer.allowed_ips)}")
        if peer.node.endpoint:
            lines.append(f"Endpoint = {peer.node.endpoint}")
            lines.append("PersistentKeepalive = 25")
    return "\n".join(lines) + "\n"


def _peers(
    nodes: tuple[TunnelNode, ...],
    *,
    local: TunnelNode,
    cidr: str,
) -> tuple[_Peer, ...]:
    by_id = {node.server_id: node for node in nodes}
    if not local.gateway:
        gateway = by_id[local.gateway_server_id]
        return (_Peer(node=gateway, allowed_ips=(cidr,)),)

    result: list[_Peer] = []
    for node in sorted(nodes, key=lambda item: item.server_id):
        if node.server_id == local.server_id:
            continue
        if not node.gateway and node.gateway_server_id != local.server_id:
            continue
        allowed = [node.host_route]
        if node.gateway:
            allowed.extend(
                child.host_route
                for child in sorted(nodes, key=lambda item: item.server_id)
                if not child.gateway
                and child.gateway_server_id == node.server_id
            )
        result.append(_Peer(node=node, allowed_ips=tuple(allowed)))
    return tuple(result)
