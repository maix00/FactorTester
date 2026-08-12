from __future__ import annotations

import base64

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from server.manager.domain.devices import (
    DeviceAuthorizationError,
    DeviceAuthorizationStore,
    DeviceChallengeStore,
    DeviceRegistry,
    PublicDeviceLimitError,
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
    assert registry.public_user_count() == 1
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


def test_public_device_authorization_is_single_use_and_stores_only_a_hash(tmp_path) -> None:
    store = DeviceAuthorizationStore(
        tmp_path / "authorizations.json",
        server_id="feat-local",
        ttl_seconds=60,
    )
    grant = store.issue(
        username="alice@default",
        target_server_id="public-main",
        target_endpoint="https://203.0.113.10:7998",
        device_name="公网上的 Mac",
    )

    payload = (tmp_path / "authorizations.json").read_text(encoding="utf-8")
    assert grant["token"] not in payload
    consumed = store.consume(grant["token"], target_server_id="public-main")
    assert consumed["username"] == "alice@default"
    assert consumed["target_endpoint"] == "https://203.0.113.10:7998"

    with pytest.raises(DeviceAuthorizationError, match="invalid or expired"):
        store.consume(grant["token"], target_server_id="public-main")


def test_public_device_authorization_is_bound_to_target_server(tmp_path) -> None:
    store = DeviceAuthorizationStore(
        tmp_path / "authorizations.json",
        server_id="feat-local",
    )
    grant = store.issue(
        username="alice@default",
        target_server_id="public-main",
        target_endpoint="https://203.0.113.10:7998",
    )

    with pytest.raises(DeviceAuthorizationError, match="invalid or expired"):
        store.consume(grant["token"], target_server_id="other-public")
