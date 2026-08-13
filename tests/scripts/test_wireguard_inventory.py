from __future__ import annotations

import base64

import pytest

from server.deployment.wireguard import (
    WireGuardInventory,
    generate_inventory_signing_key,
    render_wireguard_config,
    sign_inventory,
    verify_signed_inventory,
)


def _key(byte: int) -> str:
    return base64.b64encode(bytes([byte]) * 32).decode("ascii")


def _three_node_inventory() -> WireGuardInventory:
    return WireGuardInventory.from_dict({
        "schema_version": 1,
        "cluster_id": "factor-production",
        "generation": 7,
        "tunnels": {
            "factortester": {
                "cidr": "10.77.0.0/24",
                "nodes": [
                    {
                        "server_id": "public-a",
                        "interface_address": "10.77.0.1/24",
                        "public_key": _key(1),
                        "endpoint": "198.51.100.10:51820",
                        "listen_port": 51820,
                        "gateway": True,
                    },
                    {
                        "server_id": "public-b",
                        "interface_address": "10.77.0.2/24",
                        "public_key": _key(2),
                        "endpoint": "198.51.100.11:51820",
                        "listen_port": 51820,
                        "gateway": True,
                    },
                    {
                        "server_id": "private-feature",
                        "interface_address": "10.77.0.3/32",
                        "public_key": _key(3),
                        "gateway_server_id": "public-a",
                    },
                ],
            },
        },
    })


def _three_node_payload() -> dict[str, object]:
    inventory = _three_node_inventory()
    return {
        "schema_version": 1,
        "cluster_id": inventory.cluster_id,
        "generation": inventory.generation,
        "tunnels": {
            tunnel.name: {
                "cidr": tunnel.cidr,
                "nodes": [
                    {
                        "server_id": node.server_id,
                        "interface_address": node.interface_address,
                        "public_key": node.public_key,
                        **({"endpoint": node.endpoint} if node.endpoint else {}),
                        **({"listen_port": node.listen_port} if node.listen_port else {}),
                        **({"gateway": True} if node.gateway else {}),
                        **(
                            {"gateway_server_id": node.gateway_server_id}
                            if node.gateway_server_id else {}
                        ),
                    }
                    for node in tunnel.nodes
                ],
            }
            for tunnel in inventory.tunnels
        },
    }


def test_signed_inventory_detects_metadata_tampering() -> None:
    signing_key = generate_inventory_signing_key()
    signed = sign_inventory(_three_node_payload(), signing_key=signing_key)

    verified = verify_signed_inventory(
        signed,
        trusted_public_key=signing_key.public_key,
    )
    tampered = {**signed, "generation": 8}

    assert verified.generation == 7
    assert "private_key" not in repr(signed).lower()
    with pytest.raises(PermissionError, match="signature"):
        verify_signed_inventory(
            tampered,
            trusted_public_key=signing_key.public_key,
        )


def test_three_node_overlay_uses_one_private_bootstrap_and_public_direct_peer() -> None:
    inventory = _three_node_inventory()

    private_config = render_wireguard_config(
        inventory,
        server_id="private-feature",
        tunnel="factortester",
        private_key=_key(30),
    )
    public_a_config = render_wireguard_config(
        inventory,
        server_id="public-a",
        tunnel="factortester",
        private_key=_key(10),
    )
    public_b_config = render_wireguard_config(
        inventory,
        server_id="public-b",
        tunnel="factortester",
        private_key=_key(20),
    )

    assert private_config.count("[Peer]") == 1
    assert f"PublicKey = {_key(1)}" in private_config
    assert "AllowedIPs = 10.77.0.0/24" in private_config
    assert "Endpoint = 198.51.100.10:51820" in private_config

    assert public_a_config.count("[Peer]") == 2
    assert "PostUp = iptables -A FORWARD -i %i -o %i -j ACCEPT" in public_a_config
    assert "PostDown = iptables -D FORWARD -i %i -o %i -j ACCEPT" in public_a_config
    assert "PostUp =" not in private_config
    assert f"PublicKey = {_key(2)}" in public_a_config
    assert f"PublicKey = {_key(3)}" in public_a_config
    assert "AllowedIPs = 10.77.0.3/32" in public_a_config

    assert public_b_config.count("[Peer]") == 1
    assert f"PublicKey = {_key(1)}" in public_b_config
    assert "AllowedIPs = 10.77.0.1/32, 10.77.0.3/32" in public_b_config
    assert f"PublicKey = {_key(3)}" not in public_b_config


def test_gateway_listen_port_must_match_public_endpoint() -> None:
    payload = _three_node_payload()
    public = payload["tunnels"]["factortester"]["nodes"][0]
    public["listen_port"] = 51821

    with pytest.raises(ValueError, match="endpoint port must match listen_port"):
        WireGuardInventory.from_dict(payload)
