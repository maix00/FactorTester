"""Signed, short-lived endpoint advertisements for transfer nodes."""

from __future__ import annotations

import base64
import json
import math
import re
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from server.manager.storage.transfers.node_identities import decode_public_key
from server.manager.transfers.node_keys import NodeKey


ADVERTISEMENT_SCHEMA_VERSION = 2
_MIN_LEASE_SECONDS = 5.0
_MAX_LEASE_SECONDS = 300.0
_MAX_FUTURE_SKEW_SECONDS = 5.0
_NONCE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_SIGNED_FIELDS = frozenset({
    "schema_version",
    "node_id",
    "identity",
    "client_control_endpoint",
    "client_data_endpoint",
    "peer_control_endpoint",
    "peer_data_endpoint",
    "issued_at",
    "lease_seconds",
    "nonce",
})
_ENDPOINT_FIELDS = (
    "client_control_endpoint",
    "client_data_endpoint",
    "peer_control_endpoint",
    "peer_data_endpoint",
)


@dataclass(frozen=True, slots=True)
class VerifiedNodeAdvertisement:
    node_id: str
    identity: dict[str, str]
    issued_at: float
    expires_at: float
    lease_seconds: float
    nonce: str


def normalized_lease(value: object) -> float:
    try:
        lease = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("transfer node lease is invalid") from exc
    if not math.isfinite(lease) or not (
        _MIN_LEASE_SECONDS <= lease <= _MAX_LEASE_SECONDS
    ):
        raise ValueError("transfer node lease must be between 5 and 300 seconds")
    return lease


def signed_advertisement(
    payload: dict[str, object],
    *,
    node_key: NodeKey,
) -> dict[str, object]:
    """Return a complete advertisement signed by its node-owned key."""

    if set(payload) != _SIGNED_FIELDS:
        raise ValueError("transfer node advertisement fields are invalid")
    if payload.get("node_id") != node_key.node_id:
        raise ValueError("transfer node advertisement key owner does not match")
    if payload.get("identity") != node_key.public_record():
        raise ValueError("transfer node advertisement identity does not match key")
    result = dict(payload)
    result["signature"] = node_key.sign_bytes(_canonical_payload(result))
    return result


def verify_advertisement(
    value: dict[str, object],
    *,
    now: float,
) -> VerifiedNodeAdvertisement:
    """Verify structure, freshness, identity ownership, and Ed25519 proof."""

    if not isinstance(value, dict):
        raise ValueError("transfer node advertisement must be an object")
    expected_fields = _SIGNED_FIELDS | {"signature"}
    if set(value) != expected_fields:
        raise ValueError("transfer node advertisement fields are invalid")
    if value.get("schema_version") != ADVERTISEMENT_SCHEMA_VERSION:
        raise ValueError("unsupported transfer node advertisement")

    raw_node_id = value.get("node_id")
    node_id = str(raw_node_id or "").strip()
    raw_identity = value.get("identity")
    if (
        not isinstance(raw_node_id, str)
        or raw_node_id != node_id
        or not node_id
        or not isinstance(raw_identity, dict)
    ):
        raise ValueError("transfer node identity is required")
    identity = {
        "node_id": str(raw_identity.get("node_id") or "").strip(),
        "algorithm": str(raw_identity.get("algorithm") or "").strip(),
        "public_key": str(raw_identity.get("public_key") or "").strip(),
        "fingerprint": str(raw_identity.get("fingerprint") or "").strip(),
    }
    if set(raw_identity) != set(identity) or raw_identity != identity:
        raise ValueError("transfer node identity fields are invalid")
    if identity["node_id"] != node_id:
        raise ValueError("transfer node identity does not match advertisement")
    if identity["algorithm"] != "Ed25519":
        raise ValueError("node key algorithm must be Ed25519")

    raw_nonce = value.get("nonce")
    nonce = str(raw_nonce or "").strip()
    if (
        not isinstance(raw_nonce, str)
        or raw_nonce != nonce
        or not _NONCE.fullmatch(nonce)
    ):
        raise ValueError("transfer node advertisement nonce is invalid")
    if any(not isinstance(value.get(field), str) for field in _ENDPOINT_FIELDS):
        raise ValueError("transfer node endpoints must be strings")
    try:
        issued_at = float(value.get("issued_at"))
    except (TypeError, ValueError) as exc:
        raise ValueError("transfer node advertisement time is invalid") from exc
    current = float(now)
    if not math.isfinite(issued_at) or not math.isfinite(current):
        raise ValueError("transfer node advertisement time is invalid")
    lease = normalized_lease(value.get("lease_seconds"))
    expires_at = issued_at + lease
    if issued_at > current + _MAX_FUTURE_SKEW_SECONDS:
        raise PermissionError("transfer node advertisement is from the future")
    if expires_at <= current:
        raise PermissionError("transfer node advertisement expired")

    raw_signature = value.get("signature")
    if not isinstance(raw_signature, str):
        raise PermissionError("transfer node advertisement signature is invalid")
    signature = _decode_signature(raw_signature)
    try:
        Ed25519PublicKey.from_public_bytes(
            decode_public_key(identity["public_key"])
        ).verify(signature, _canonical_payload(value))
    except (InvalidSignature, TypeError, ValueError) as exc:
        raise PermissionError("transfer node advertisement signature is invalid") from exc
    return VerifiedNodeAdvertisement(
        node_id=node_id,
        identity=identity,
        issued_at=issued_at,
        expires_at=expires_at,
        lease_seconds=lease,
        nonce=nonce,
    )


def _canonical_payload(value: dict[str, object]) -> bytes:
    payload = {key: value[key] for key in sorted(_SIGNED_FIELDS)}
    try:
        rendered = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("transfer node advertisement is not serializable") from exc
    return rendered.encode("utf-8")


def _decode_signature(value: str) -> bytes:
    try:
        result = base64.b64decode(
            value + "=" * (-len(value) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, TypeError) as exc:
        raise PermissionError("transfer node advertisement signature is invalid") from exc
    if len(result) != 64:
        raise PermissionError("transfer node advertisement signature is invalid")
    return result
