"""One-time challenge authentication for node control requests."""

from __future__ import annotations

import hashlib
import secrets
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from server.manager.storage.transfers.node_identities import (
    NodeIdentityRegistry,
    decode_public_key,
)
from server.manager.transfers.node_keys import _decode, request_signature_message
from server.manager.transfers.node_models import NodeChallenge, NodeIdentityRecord


class NodeAuthenticator:
    def __init__(
        self,
        registry: NodeIdentityRegistry,
        *,
        challenge_ttl: float = 30.0,
    ) -> None:
        self.registry = registry
        self.challenge_ttl = max(1.0, min(120.0, float(challenge_ttl)))

    def issue_challenge(
        self,
        node_id: str,
        *,
        now: float | None = None,
    ) -> NodeChallenge:
        identity = self.registry.require(node_id)
        current = time.time() if now is None else float(now)
        challenge_id = secrets.token_hex(16)
        challenge = secrets.token_urlsafe(32)
        expires_at = current + self.challenge_ttl
        with self.registry._connect() as connection:
            connection.execute(
                """
                INSERT INTO transfer_node_challenges(
                    challenge_id, challenge_hash, node_id, issued_at, expires_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    challenge_id,
                    hashlib.sha256(challenge.encode("utf-8")).hexdigest(),
                    identity.node_id,
                    current,
                    expires_at,
                ),
            )
        return NodeChallenge(
            challenge_id=challenge_id,
            challenge=challenge,
            node_id=identity.node_id,
            expires_at=expires_at,
        )

    def verify(
        self,
        *,
        node_id: str,
        challenge: str,
        signature: str,
        method: str,
        path: str,
        body: bytes,
        now: float | None = None,
    ) -> NodeIdentityRecord:
        identity = self.registry.require(node_id)
        current = time.time() if now is None else float(now)
        challenge_hash = hashlib.sha256(challenge.encode("utf-8")).hexdigest()
        with self.registry._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM transfer_node_challenges
                WHERE challenge_hash=? AND node_id=?
                """,
                (challenge_hash, identity.node_id),
            ).fetchone()
            if row is None or row["used_at"] is not None:
                raise PermissionError("node challenge is invalid or already used")
            if float(row["expires_at"]) <= current:
                raise PermissionError("node challenge expired")
            try:
                Ed25519PublicKey.from_public_bytes(
                    decode_public_key(identity.public_key)
                ).verify(
                    _decode(signature),
                    request_signature_message(
                        challenge=challenge,
                        method=method,
                        path=path,
                        body=body,
                    ),
                )
            except (InvalidSignature, ValueError, TypeError) as exc:
                raise PermissionError("node signature is invalid") from exc
            connection.execute(
                "UPDATE transfer_node_challenges SET used_at=? "
                "WHERE challenge_id=?",
                (current, str(row["challenge_id"])),
            )
        return identity

