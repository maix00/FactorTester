"""Local cache and authority Adapter for enrolled node public keys."""

from __future__ import annotations

import base64
import hashlib
import time
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from server.manager.storage.transfers.database import TransferDatabase
from server.manager.storage.transfers.records import required
from server.manager.transfers.node_models import NodeIdentityRecord


def decode_public_key(value: str) -> bytes:
    try:
        result = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError) as exc:
        raise ValueError("node public key is invalid") from exc
    if len(result) != 32:
        raise ValueError("node public key must contain 32 bytes")
    Ed25519PublicKey.from_public_bytes(result)
    return result


def _record(row) -> NodeIdentityRecord:
    rotated = row["rotated_at"]
    revoked = row["revoked_at"]
    return NodeIdentityRecord(
        node_id=str(row["node_id"]),
        algorithm=str(row["algorithm"]),
        public_key=str(row["public_key"]),
        fingerprint=str(row["fingerprint"]),
        enrolled_at=float(row["enrolled_at"]),
        rotated_at=float(rotated) if rotated is not None else None,
        revoked_at=float(revoked) if revoked is not None else None,
    )


class NodeIdentityRegistry(TransferDatabase):
    def __init__(self, path: str | Path, *, server_id: str) -> None:
        super().__init__(path, server_id=server_id)

    def enroll(
        self,
        value: dict[str, str],
        *,
        now: float | None = None,
    ) -> NodeIdentityRecord:
        current = time.time() if now is None else float(now)
        node_id = required(value.get("node_id"), field="node_id")
        if value.get("algorithm") != "Ed25519":
            raise ValueError("node key algorithm must be Ed25519")
        public_key = required(value.get("public_key"), field="public_key")
        fingerprint = hashlib.sha256(decode_public_key(public_key)).hexdigest()
        supplied = str(value.get("fingerprint") or "").strip()
        if supplied and supplied != fingerprint:
            raise ValueError("node key fingerprint does not match")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM transfer_node_identities WHERE node_id=?",
                (node_id,),
            ).fetchone()
            if row is not None:
                if (
                    str(row["public_key"]) != public_key
                    or str(row["fingerprint"]) != fingerprint
                ):
                    raise ValueError("node key change requires explicit rotation")
                return _record(row)
            connection.execute(
                """
                INSERT INTO transfer_node_identities(
                    node_id, algorithm, public_key, fingerprint, enrolled_at
                ) VALUES (?, 'Ed25519', ?, ?, ?)
                """,
                (node_id, public_key, fingerprint, current),
            )
            stored = connection.execute(
                "SELECT * FROM transfer_node_identities WHERE node_id=?",
                (node_id,),
            ).fetchone()
        return _record(stored)

    def require(self, node_id: str) -> NodeIdentityRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM transfer_node_identities WHERE node_id=?",
                (required(node_id, field="node_id"),),
            ).fetchone()
        if row is None:
            raise KeyError("node identity not found")
        identity = _record(row)
        if identity.revoked_at is not None:
            raise PermissionError("node identity was revoked")
        return identity

    def rotate(
        self,
        *,
        node_id: str,
        expected_fingerprint: str,
        public_key: str,
        now: float | None = None,
    ) -> NodeIdentityRecord:
        current = time.time() if now is None else float(now)
        identifier = required(node_id, field="node_id")
        fingerprint = hashlib.sha256(decode_public_key(public_key)).hexdigest()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM transfer_node_identities WHERE node_id=?",
                (identifier,),
            ).fetchone()
            if row is None:
                raise KeyError("node identity not found")
            if str(row["fingerprint"]) != str(expected_fingerprint):
                raise RuntimeError("node identity changed before rotation")
            connection.execute(
                """
                UPDATE transfer_node_identities
                SET public_key=?, fingerprint=?, rotated_at=?, revoked_at=NULL
                WHERE node_id=?
                """,
                (public_key, fingerprint, current, identifier),
            )
            updated = connection.execute(
                "SELECT * FROM transfer_node_identities WHERE node_id=?",
                (identifier,),
            ).fetchone()
        return _record(updated)

