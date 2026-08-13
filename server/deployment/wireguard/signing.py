"""Ed25519 trust envelope for public WireGuard deployment metadata."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .inventory import WireGuardInventory


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: object, *, field: str, length: int = 32) -> bytes:
    selected = str(value or "").strip()
    try:
        decoded = base64.urlsafe_b64decode(
            selected + "=" * (-len(selected) % 4),
        )
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{field} is not valid base64") from exc
    if len(decoded) != length:
        raise ValueError(f"{field} must decode to {length} bytes")
    return decoded


def _key_id(public_key: bytes) -> str:
    return hashlib.sha256(public_key).hexdigest()


def _canonical(value: dict[str, object]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class InventorySigningKey:
    private_key: str
    public_key: str
    key_id: str


def generate_inventory_signing_key() -> InventorySigningKey:
    private = Ed25519PrivateKey.generate()
    private_bytes = private.private_bytes_raw()
    public_bytes = private.public_key().public_bytes_raw()
    return InventorySigningKey(
        private_key=_encode(private_bytes),
        public_key=_encode(public_bytes),
        key_id=_key_id(public_bytes),
    )


def sign_inventory(
    value: dict[str, object],
    *,
    signing_key: InventorySigningKey,
) -> dict[str, object]:
    if "signature" in value:
        raise ValueError("unsigned inventory must not already contain signature")
    # Validate before signing so a trusted signature can never bless private
    # key material, duplicate addresses, or an invalid gateway assignment.
    WireGuardInventory.from_dict(value)
    private_bytes = _decode(
        signing_key.private_key, field="inventory signing private key",
    )
    public_bytes = _decode(
        signing_key.public_key, field="inventory signing public key",
    )
    private = Ed25519PrivateKey.from_private_bytes(private_bytes)
    derived_public = private.public_key().public_bytes_raw()
    if derived_public != public_bytes:
        raise ValueError("inventory signing key pair does not match")
    key_id = _key_id(public_bytes)
    if signing_key.key_id != key_id:
        raise ValueError("inventory signing key id does not match")
    payload = json.loads(json.dumps(value, ensure_ascii=False))
    return {
        **payload,
        "signature": {
            "algorithm": "Ed25519",
            "key_id": key_id,
            "value": _encode(private.sign(_canonical(payload))),
        },
    }


def verify_signed_inventory(
    value: dict[str, object],
    *,
    trusted_public_key: str,
) -> WireGuardInventory:
    if not isinstance(value, dict):
        raise ValueError("signed inventory must be an object")
    signature = value.get("signature")
    if not isinstance(signature, dict):
        raise PermissionError("inventory signature is required")
    if signature.get("algorithm") != "Ed25519":
        raise PermissionError("inventory signature algorithm is not trusted")
    public_bytes = _decode(
        trusted_public_key, field="trusted inventory public key",
    )
    if str(signature.get("key_id") or "") != _key_id(public_bytes):
        raise PermissionError("inventory signature key is not trusted")
    raw_signature = _decode(
        signature.get("value"), field="inventory signature", length=64,
    )
    payload = {key: item for key, item in value.items() if key != "signature"}
    try:
        Ed25519PublicKey.from_public_bytes(public_bytes).verify(
            raw_signature,
            _canonical(payload),
        )
    except InvalidSignature as exc:
        raise PermissionError("inventory signature verification failed") from exc
    return WireGuardInventory.from_dict(payload)
