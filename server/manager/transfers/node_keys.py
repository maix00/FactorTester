"""Node-owned Ed25519 key creation, persistence, and request signing."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def request_signature_message(
    *,
    challenge: str,
    method: str,
    path: str,
    body: bytes,
) -> bytes:
    digest = hashlib.sha256(body).hexdigest()
    return "\n".join((challenge, method.upper(), path, digest)).encode("utf-8")


@dataclass(frozen=True, slots=True)
class NodeKey:
    node_id: str
    private_key: str
    public_key: str
    fingerprint: str

    @classmethod
    def load_or_create(cls, path: str | Path, *, node_id: str) -> "NodeKey":
        target = Path(path).expanduser().resolve()
        identity = str(node_id or "").strip()
        if not identity:
            raise ValueError("node_id is required")
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls._create(target, node_id=identity)
        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise ValueError("node identity key file is invalid")
        stored_id = str(payload.get("node_id") or "").strip()
        if stored_id != identity:
            raise ValueError(f"node identity key belongs to {stored_id or 'unknown'}")
        private_value = str(payload.get("private_key") or "")
        private = Ed25519PrivateKey.from_private_bytes(_decode(private_value))
        return cls._from_private(identity, private, private_value=private_value)

    @classmethod
    def _create(cls, path: Path, *, node_id: str) -> "NodeKey":
        path.parent.mkdir(parents=True, exist_ok=True)
        private = Ed25519PrivateKey.generate()
        private_value = _encode(private.private_bytes_raw())
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps({
                "version": 1,
                "algorithm": "Ed25519",
                "node_id": node_id,
                "private_key": private_value,
            }, sort_keys=True),
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        return cls._from_private(node_id, private, private_value=private_value)

    @classmethod
    def _from_private(
        cls,
        node_id: str,
        private: Ed25519PrivateKey,
        *,
        private_value: str,
    ) -> "NodeKey":
        public_bytes = private.public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw,
        )
        return cls(
            node_id=node_id,
            private_key=private_value,
            public_key=_encode(public_bytes),
            fingerprint=hashlib.sha256(public_bytes).hexdigest(),
        )

    def public_record(self) -> dict[str, str]:
        return {
            "node_id": self.node_id,
            "algorithm": "Ed25519",
            "public_key": self.public_key,
            "fingerprint": self.fingerprint,
        }

    def sign_request(
        self,
        *,
        challenge: str,
        method: str,
        path: str,
        body: bytes,
    ) -> str:
        return self.sign_bytes(request_signature_message(
            challenge=challenge,
            method=method,
            path=path,
            body=body,
        ))

    def sign_bytes(self, value: bytes) -> str:
        """Sign one protocol-owned canonical byte sequence."""

        if not isinstance(value, bytes):
            raise TypeError("signed value must be bytes")
        private = Ed25519PrivateKey.from_private_bytes(_decode(self.private_key))
        return _encode(private.sign(value))
