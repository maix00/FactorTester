"""Hash-addressed local-file Evidence bytes for the shared data plane."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


class EvidenceFileStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()

    @staticmethod
    def digest_from_id(object_id: str) -> str:
        parts = str(object_id or "").split(":")
        if len(parts) != 3 or parts[:2] != ["evidence-file", "v1"]:
            raise ValueError("Evidence file object id is invalid")
        digest = parts[2].lower()
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("Evidence file object hash is invalid")
        return digest

    def path(self, object_id: str) -> Path:
        digest = self.digest_from_id(object_id)
        return self.root / digest[:2] / digest

    def resolve(self, object_id: str, *, size: int, sha256: str) -> Path:
        digest = self.digest_from_id(object_id)
        if digest != str(sha256 or "").lower():
            raise RuntimeError("Evidence file identity changed after authorization")
        path = self.path(object_id)
        if not path.is_file():
            raise FileNotFoundError("Evidence file has not been uploaded")
        if path.stat().st_size != int(size):
            raise RuntimeError("Evidence file size changed after authorization")
        return path

    def store(self, object_id: str, staged_path: Path, *, size: int, sha256: str) -> Path:
        digest = self.digest_from_id(object_id)
        expected = str(sha256 or "").lower()
        if digest != expected:
            raise ValueError("Evidence file object id does not match its hash")
        raw_size = staged_path.stat().st_size
        if raw_size != int(size):
            raise ValueError("Evidence file upload size is invalid")
        hasher = hashlib.sha256()
        with staged_path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                hasher.update(chunk)
        if hasher.hexdigest() != expected:
            raise ValueError("Evidence file upload hash is invalid")
        destination = self.path(object_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged_path, destination)
        destination.chmod(0o600)
        return destination


class EvidenceFileOriginAdapter:
    def __init__(self, root: str | Path) -> None:
        self.store = EvidenceFileStore(root)

    def __call__(self, transfer) -> Path:
        return self.store.resolve(
            transfer.object_id,
            size=transfer.expected_size,
            sha256=transfer.expected_sha256,
        )


class EvidenceFileDestinationAdapter:
    def __init__(self, root: str | Path) -> None:
        self.store = EvidenceFileStore(root)

    def __call__(self, context, staged_path: Path) -> Path:
        transfer = context.transfer
        return self.store.store(
            transfer.object_id,
            staged_path,
            size=transfer.expected_size,
            sha256=transfer.expected_sha256,
        )


__all__ = [
    "EvidenceFileDestinationAdapter", "EvidenceFileOriginAdapter", "EvidenceFileStore",
]
