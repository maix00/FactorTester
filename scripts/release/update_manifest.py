"""Create one compact signed stable/beta update-channel manifest."""

from __future__ import annotations

import argparse
import base64
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import tempfile

from tools.cli.release.update_channel import (
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
        "sha256": _file_sha256(dmg),
        "minimum_client": minimum_client,
        "mandatory": mandatory,
        "published_at": published_at,
    }
    signature = _sign(
        canonical_unsigned_update_manifest(manifest), private_key
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
    if _file_sha256(dmg) != validated.dmg_sha256:
        raise ValueError("DMG SHA256 does not match signed update manifest")


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sign(payload: bytes, private_key: Path) -> bytes:
    with tempfile.TemporaryDirectory(prefix="factortester-update-sign-") as raw:
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--build", required=True, type=int)
    parser.add_argument("--channel", choices=("stable", "beta"), required=True)
    parser.add_argument("--dmg", required=True, type=Path)
    parser.add_argument("--dmg-url", required=True)
    parser.add_argument("--minimum-client", required=True)
    parser.add_argument("--mandatory", action="store_true")
    parser.add_argument("--published-at", required=True)
    parser.add_argument("--private-key", required=True, type=Path)
    parser.add_argument("--public-key", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = vars(parser.parse_args())
    output = args.pop("output")
    write_update_manifest(output, create_update_manifest(**args))
    print(output)


if __name__ == "__main__":
    main()
