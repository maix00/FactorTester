from __future__ import annotations

import base64
from hashlib import sha256 as hash_sha256
import json
from pathlib import Path
import subprocess

import pytest

from tools.cli.release.contracts import (
    canonical_unsigned_manifest,
    validate_release_manifest,
)


def _keys(root: Path) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    private_key = root / "private.pem"
    public_key = root / "public.pem"
    subprocess.run(
        [
            "openssl",
            "genpkey",
            "-algorithm",
            "EC",
            "-pkeyopt",
            "ec_paramgen_curve:P-256",
            "-out",
            str(private_key),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "openssl",
            "pkey",
            "-in",
            str(private_key),
            "-pubout",
            "-out",
            str(public_key),
        ],
        check=True,
        capture_output=True,
    )
    return private_key, public_key


def signed_manifest(
    root: Path,
    *,
    version: str = "1.2.3",
    sha256: str = "a" * 64,
    size: int = 12,
    kind: str = "python-wheel",
    filename: str = "factortester.whl",
) -> tuple[dict, Path]:
    private_key, public_key = _keys(root)
    manifest = {
        "schema_version": 1,
        "release": {
            "id": f"factortester-client-{version}",
            "version": version,
            "source_revision": "a" * 40,
        },
        "client_protocol": {"minimum": 1, "maximum": 1},
        "assets": [{
            "id": "factortester-cli",
            "kind": kind,
            "filename": filename,
            "url": f"https://example.invalid/{filename}",
            "sha256": sha256,
            "size": size,
        }],
    }
    payload = root / "manifest.json"
    signature = root / "manifest.sig"
    payload.write_bytes(canonical_unsigned_manifest(manifest))
    subprocess.run(
        [
            "openssl",
            "dgst",
            "-sha256",
            "-sign",
            str(private_key),
            "-out",
            str(signature),
            str(payload),
        ],
        check=True,
        capture_output=True,
    )
    manifest["signature"] = {
        "algorithm": "ecdsa-sha256",
        "key_id": hash_sha256(public_key.read_bytes()).hexdigest(),
        "value": base64.b64encode(signature.read_bytes()).decode("ascii"),
    }
    return manifest, public_key


def test_signed_release_manifest_verifies_and_is_compact(
    tmp_path: Path,
) -> None:
    manifest, public_key = signed_manifest(tmp_path)

    validated = validate_release_manifest(manifest, public_key=public_key)

    assert validated.version == "1.2.3"
    assert validated.source_revision == "a" * 40
    assert validated.manifest_hash
    assert validated.assets[0].asset_id == "factortester-cli"
    assert len(json.dumps(manifest)) < 4_000


def test_manifest_signature_rejects_tampering(tmp_path: Path) -> None:
    manifest, public_key = signed_manifest(tmp_path)
    manifest["assets"][0]["size"] = 13

    with pytest.raises(ValueError, match="signature"):
        validate_release_manifest(manifest, public_key=public_key)


def test_manifest_rejects_untrusted_key_id(tmp_path: Path) -> None:
    manifest, public_key = signed_manifest(tmp_path)
    manifest["signature"]["key_id"] = "0" * 64

    with pytest.raises(ValueError, match="key ID"):
        validate_release_manifest(manifest, public_key=public_key)


def test_manifest_rejects_incompatible_protocol(tmp_path: Path) -> None:
    manifest, public_key = signed_manifest(tmp_path)
    manifest["client_protocol"] = {"minimum": 3, "maximum": 4}
    private_key, public_key = _keys(tmp_path / "replacement")
    payload = tmp_path / "replacement-payload"
    signature = tmp_path / "replacement-signature"
    payload.write_bytes(canonical_unsigned_manifest(manifest))
    subprocess.run(
        [
            "openssl", "dgst", "-sha256", "-sign", str(private_key),
            "-out", str(signature), str(payload),
        ],
        check=True,
        capture_output=True,
    )
    manifest["signature"]["value"] = base64.b64encode(
        signature.read_bytes()
    ).decode("ascii")
    manifest["signature"]["key_id"] = hash_sha256(
        public_key.read_bytes()
    ).hexdigest()

    with pytest.raises(ValueError, match="protocol"):
        validate_release_manifest(manifest, public_key=public_key)
