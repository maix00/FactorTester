from __future__ import annotations

import os

import pytest

from server.manager.storage.transfers.node_identities import NodeIdentityRegistry
from server.manager.transfers.node_keys import NodeKey
from server.manager.transfers.security import NodeAuthenticator


def test_node_private_key_is_local_persistent_and_owner_only(tmp_path) -> None:
    path = tmp_path / "node-identity.key"

    first = NodeKey.load_or_create(path, node_id="office-a")
    restarted = NodeKey.load_or_create(path, node_id="office-a")

    assert restarted.public_key == first.public_key
    assert restarted.fingerprint == first.fingerprint
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert first.private_key not in first.public_record()
    with pytest.raises(ValueError, match="belongs to"):
        NodeKey.load_or_create(path, node_id="other-node")


def test_node_enrollment_is_idempotent_and_key_change_requires_rotation(
    tmp_path,
) -> None:
    registry = NodeIdentityRegistry(
        tmp_path / "transfers.sqlite", server_id="public-b1",
    )
    key = NodeKey.load_or_create(tmp_path / "office-a.key", node_id="office-a")
    changed = NodeKey.load_or_create(
        tmp_path / "office-a-changed.key", node_id="office-a",
    )

    first = registry.enroll(key.public_record(), now=100.0)
    duplicate = registry.enroll(key.public_record(), now=101.0)

    assert duplicate == first
    assert first.node_id == "office-a"
    assert first.public_key == key.public_key
    with pytest.raises(ValueError, match="rotation"):
        registry.enroll(changed.public_record(), now=102.0)

    rotated = registry.rotate(
        node_id="office-a",
        expected_fingerprint=first.fingerprint,
        public_key=changed.public_key,
        now=103.0,
    )
    assert rotated.public_key == changed.public_key
    assert rotated.fingerprint != first.fingerprint


def test_challenge_signature_binds_node_method_path_and_body_and_is_one_time(
    tmp_path,
) -> None:
    registry = NodeIdentityRegistry(
        tmp_path / "transfers.sqlite", server_id="public-b1",
    )
    key = NodeKey.load_or_create(tmp_path / "office-a.key", node_id="office-a")
    registry.enroll(key.public_record(), now=100.0)
    authenticator = NodeAuthenticator(registry, challenge_ttl=30.0)
    challenge = authenticator.issue_challenge("office-a", now=101.0)
    body = b'{"after_sequence":6}'
    signature = key.sign_request(
        challenge=challenge.challenge,
        method="POST",
        path="/api/federation/node/control/poll",
        body=body,
    )

    identity = authenticator.verify(
        node_id="office-a",
        challenge=challenge.challenge,
        signature=signature,
        method="POST",
        path="/api/federation/node/control/poll",
        body=body,
        now=102.0,
    )

    assert identity.node_id == "office-a"
    with pytest.raises(PermissionError, match="challenge"):
        authenticator.verify(
            node_id="office-a",
            challenge=challenge.challenge,
            signature=signature,
            method="POST",
            path="/api/federation/node/control/poll",
            body=body,
            now=103.0,
        )

    changed = authenticator.issue_challenge("office-a", now=104.0)
    changed_signature = key.sign_request(
        challenge=changed.challenge,
        method="POST",
        path="/api/federation/node/control/poll",
        body=body,
    )
    with pytest.raises(PermissionError, match="signature"):
        authenticator.verify(
            node_id="office-a",
            challenge=changed.challenge,
            signature=changed_signature,
            method="POST",
            path="/different",
            body=body,
            now=105.0,
        )


def test_expired_challenge_is_rejected(tmp_path) -> None:
    registry = NodeIdentityRegistry(
        tmp_path / "transfers.sqlite", server_id="public-b1",
    )
    key = NodeKey.load_or_create(tmp_path / "office-a.key", node_id="office-a")
    registry.enroll(key.public_record(), now=100.0)
    authenticator = NodeAuthenticator(registry, challenge_ttl=5.0)
    challenge = authenticator.issue_challenge("office-a", now=101.0)
    signature = key.sign_request(
        challenge=challenge.challenge,
        method="GET",
        path="/api/federation/node/control",
        body=b"",
    )

    with pytest.raises(PermissionError, match="expired"):
        authenticator.verify(
            node_id="office-a",
            challenge=challenge.challenge,
            signature=signature,
            method="GET",
            path="/api/federation/node/control",
            body=b"",
            now=107.0,
        )
