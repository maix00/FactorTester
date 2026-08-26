"""Author and verify signed client update manifests.

This module is part of the distributed client wheel.  Release retargeting is
an operator CLI capability and must not import the repository-only ``scripts``
package.
"""

from __future__ import annotations

import base64
import json
import subprocess
import tempfile
from hashlib import sha256
from pathlib import Path

from .update_channel import (
    canonical_unsigned_update_manifest,
    validate_update_manifest,
)


def create_update_manifest(
    *,
    version: str,
    build: int,
    channel: str,
    dmg: Path,
    dmg_url: str,
    minimum_client: str,
    mandatory: bool,
    published_at: str,
    private_key: Path,
    public_key: Path,
) -> dict:
    manifest = {
        "schema_version": 1,
        "version": version,
        "build": build,
        "channel": channel,
        "dmg_url": dmg_url,
        "sha256": file_sha256(dmg),
        "minimum_client": minimum_client,
        "mandatory": mandatory,
        "published_at": published_at,
    }
    signature = _sign(
        canonical_unsigned_update_manifest(manifest), private_key,
    )
    manifest["signature"] = {
        "algorithm": "ecdsa-sha256",
        "key_id": sha256(public_key.read_bytes()).hexdigest(),
        "value": base64.b64encode(signature).decode("ascii"),
    }
    validate_update_manifest(
        manifest,
        public_key=public_key,
        expected_channel=channel,
    )
    return manifest


def write_update_manifest(path: Path, manifest: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n",
        encoding="utf-8",
    )
    return path


def verify_installer(
    dmg: Path,
    manifest: dict,
    *,
    public_key: Path,
    channel: str,
) -> None:
    validated = validate_update_manifest(
        manifest,
        public_key=public_key,
        expected_channel=channel,
    )
    if file_sha256(dmg) != validated.dmg_sha256:
        raise ValueError("DMG SHA256 does not match signed update manifest")


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sign(payload: bytes, private_key: Path) -> bytes:
    with tempfile.TemporaryDirectory(
        prefix="factortester-update-sign-",
    ) as raw:
        root = Path(raw)
        source = root / "manifest.json"
        signature = root / "manifest.sig"
        source.write_bytes(payload)
        subprocess.run(
            [
                "openssl", "dgst", "-sha256", "-sign", str(private_key),
                "-out", str(signature), str(source),
            ],
            check=True,
            capture_output=True,
        )
        return signature.read_bytes()


__all__ = [
    "create_update_manifest",
    "file_sha256",
    "verify_installer",
    "write_update_manifest",
]
