"""Validated multi-node WireGuard deployment inventory."""

from .inventory import (
    TunnelNode,
    TunnelSpec,
    WireGuardInventory,
)
from .render import render_wireguard_config
from .signing import (
    InventorySigningKey,
    generate_inventory_signing_key,
    sign_inventory,
    verify_signed_inventory,
)

__all__ = [
    "TunnelNode",
    "TunnelSpec",
    "WireGuardInventory",
    "InventorySigningKey",
    "generate_inventory_signing_key",
    "render_wireguard_config",
    "sign_inventory",
    "verify_signed_inventory",
]
