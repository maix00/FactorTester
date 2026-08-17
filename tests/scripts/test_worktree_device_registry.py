from __future__ import annotations

import base64
import json

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from server.manager.domain.devices import (
    DeviceChallengeStore,
    DeviceRegistry,
)
from server.manager.domain.device_clients import describe_client, observed_ip


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


def test_device_registry_keeps_only_minimal_client_and_ip_audit_metadata(tmp_path) -> None:
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
        client_type="browser",
        client_name="Apple Safari 18.1",
        enrollment_ip="203.0.113.8",
    )

    assert enrolled["source_server_id"] == "feat-local"
    assert enrolled["public_key_fingerprint"]
    assert "public_key" not in enrolled
    assert "mac" not in enrolled
    assert "imei" not in enrolled
    assert "user_agent" not in enrolled
    assert enrolled["client_type"] == "browser"
    assert enrolled["client_name"] == "Apple Safari 18.1"
    assert enrolled["enrollment_ip"] == "203.0.113.8"
    assert registry.verify(
        device_id=device_id,
        public_key=public_key,
        challenge=challenge,
        signature=_signature(private_key, challenge),
        last_seen_ip="203.0.113.9",
    )["username"] == "alice@default"
    assert registry.list(username="alice@default")[0]["last_seen_ip"] == "203.0.113.9"

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


def test_existing_device_snapshot_is_migrated_to_allowlist_policy(tmp_path) -> None:
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = _jwk(private_key.public_key())
    path = tmp_path / "devices.json"
    path.write_text(json.dumps({
        "schema_version": 3,
        "server_id": "public-main",
        "generation": 2,
        "devices": {
            "device-legacy-123456": {
                "device_id": "device-legacy-123456",
                "public_key": public_key,
                "username": "alice@default",
                "enabled": True,
                "public_access": False,
                "quota_exempt": False,
            },
        },
        "sources": {},
    }), encoding="utf-8")

    registry = DeviceRegistry(path, server_id="public-main", public_server=True)
    record = registry.list(username="alice@default")[0]

    assert record["public_access"] is True
    assert record["quota_exempt"] is True
    persisted = json.loads(path.read_text(encoding="utf-8"))
    migrated = persisted["devices"]["device-legacy-123456"]
    assert migrated["public_access"] is True
    assert migrated["quota_exempt"] is True


def test_public_server_accepts_all_allowlisted_devices(tmp_path) -> None:
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = _jwk(private_key.public_key())
    registry = DeviceRegistry(
        tmp_path / "devices.json",
        server_id="public-main",
        public_server=True,
    )

    for index in range(5):
        registry.enroll(
            username="alice@default",
            device_id=f"device-public-{index:06d}",
            public_key=public_key,
        )

    assert registry.public_device_count(username="alice@default") == 5

    assert registry.public_user_count() == 1
    registry.revoke("device-public-000000")
    assert registry.public_device_count(username="alice@default") == 4


def test_all_enrolled_devices_are_allowlisted_devices(tmp_path) -> None:
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = _jwk(private_key.public_key())
    registry = DeviceRegistry(
        tmp_path / "devices.json",
        server_id="public-main",
        public_server=True,
    )

    for index in range(5):
        record = registry.enroll(
            username="alice@default",
            device_id=f"device-auto-{index:06d}",
            public_key=public_key,
        )
        assert record["quota_exempt"] is True

    assert registry.public_device_count(username="alice@default") == 5
    assert registry.public_device_total_count(username="alice@default") == 5


def test_device_challenges_are_one_use() -> None:
    store = DeviceChallengeStore(ttl_seconds=30)
    challenge_id, challenge = store.issue()

    assert store.consume(challenge_id) == challenge
    with pytest.raises(PermissionError, match="expired"):
        store.consume(challenge_id)


def test_device_client_description_discards_raw_user_agent() -> None:
    browser = describe_client(
        user_agent=(
            "Mozilla/5.0 AppleWebKit/537.36 "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
    )
    native = describe_client(
        user_agent="FactorTester-Swift/1",
        client_hint="swift",
    )

    assert browser == {
        "client_type": "browser",
        "client_name": "Google Chrome 126.0.0.0",
    }
    assert native == {
        "client_type": "swift",
        "client_name": "FactorTester Swift 1",
    }
    assert observed_ip("2001:db8::1") == "2001:db8::1"
    assert observed_ip("not-an-ip") == ""
