from __future__ import annotations

import base64

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from server.manager.domain.devices import (
    DeviceChallengeStore,
    DeviceRegistry,
    PublicDeviceLimitError,
)


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _jwk(public_key: ec.EllipticCurvePublicKey) -> dict[str, str]:
    numbers = public_key.public_numbers()
    return {
        "kty": "EC",
        "crv": "P-256",
        "x": _b64url(numbers.x.to_bytes(32, "big")),
        "y": _b64url(numbers.y.to_bytes(32, "big")),
    }


def _signature(private_key: ec.EllipticCurvePrivateKey, message: bytes) -> str:
    der = private_key.sign(message, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    return _b64url(r.to_bytes(32, "big") + s.to_bytes(32, "big"))


def test_device_registry_enrolls_verifies_and_revokes_without_device_metadata(tmp_path) -> None:
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = _jwk(private_key.public_key())
    registry = DeviceRegistry(tmp_path / "devices.json", server_id="feat-local")
    device_id = "device-opaque-123456"
    challenge = b"one-time-device-challenge"

    enrolled = registry.enroll(
        username="alice@default",
        device_id=device_id,
        public_key=public_key,
        device_name="研究浏览器",
    )

    assert enrolled["source_server_id"] == "feat-local"
    assert enrolled["public_key_fingerprint"]
    assert "public_key" not in enrolled
    assert "mac" not in enrolled
    assert "imei" not in enrolled
    assert registry.verify(
        device_id=device_id,
        public_key=public_key,
        challenge=challenge,
        signature=_signature(private_key, challenge),
    )["username"] == "alice@default"

    with pytest.raises(PermissionError, match="signature is invalid"):
        registry.verify(
            device_id=device_id,
            public_key=public_key,
            challenge=challenge,
            signature=_signature(private_key, b"wrong challenge"),
        )

    assert registry.revoke(device_id)["enabled"] is False
    with pytest.raises(PermissionError, match="approved"):
        registry.verify(
            device_id=device_id,
            public_key=public_key,
            challenge=b"after revoke",
            signature=_signature(private_key, b"after revoke"),
        )


def test_public_server_enforces_three_active_devices_per_user(tmp_path) -> None:
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = _jwk(private_key.public_key())
    registry = DeviceRegistry(
        tmp_path / "devices.json",
        server_id="public-main",
        public_server=True,
    )

    for index in range(3):
        registry.enroll(
            username="alice@default",
            device_id=f"device-public-{index:06d}",
            public_key=public_key,
        )

    assert registry.public_device_count(username="alice@default") == 3
    with pytest.raises(PublicDeviceLimitError, match="limit reached") as error:
        registry.enroll(
            username="alice@default",
            device_id="device-public-000003",
            public_key=public_key,
        )
    assert error.value.count == 3

    registry.revoke("device-public-000000")
    assert registry.public_device_count(username="alice@default") == 2
    registry.enroll(
        username="alice@default",
        device_id="device-public-000003",
        public_key=public_key,
    )
    assert registry.public_device_count(username="alice@default") == 3


def test_device_challenges_are_one_use() -> None:
    store = DeviceChallengeStore(ttl_seconds=30)
    challenge_id, challenge = store.issue()

    assert store.consume(challenge_id) == challenge
    with pytest.raises(PermissionError, match="expired"):
        store.consume(challenge_id)
