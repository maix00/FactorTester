"""Create the compact signed release manifest."""

from __future__ import annotations

import base64
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import tempfile

from tools.cli.protocol import CLIENT_PROTOCOL_CURRENT, CLIENT_PROTOCOL_MINIMUM
from tools.cli.release.contracts import canonical_unsigned_manifest


def create_manifest(
    *,
    version: str,
    revision: str,
    base_url: str,
    assets: list[Path],
    private_key: Path,
    public_key: Path,
) -> dict:
    _assert_key_pair(private_key, public_key)
    manifest = {
        "schema_version": 1,
        "release": {
            "id": f"factortester-client-{version}",
            "version": version,
            "source_revision": revision,
        },
        "client_protocol": {
            "minimum": CLIENT_PROTOCOL_MINIMUM,
            "maximum": CLIENT_PROTOCOL_CURRENT,
        },
        "assets": [_asset(path, base_url) for path in sorted(assets)],
    }
    payload = canonical_unsigned_manifest(manifest)
    signature = _sign(payload, private_key)
    manifest["signature"] = {
        "algorithm": "ecdsa-sha256",
        "key_id": sha256(public_key.read_bytes()).hexdigest(),
        "value": base64.b64encode(signature).decode("ascii"),
    }
    return manifest


def write_manifest(path: Path, manifest: dict) -> Path:
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    return path


def _asset(path: Path, base_url: str) -> dict:
    return {
        "id": path.stem.replace("_", "-"),
        "kind": _kind(path.name),
        "filename": path.name,
        "url": f"{base_url.rstrip('/')}/{path.name}",
        "sha256": sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
    }


def _kind(name: str) -> str:
    if name.endswith(".whl"):
        return (
            "harness-wheel"
            if name.startswith("cli_anything_factortester_research-")
            else "python-wheel"
        )
    if name in {"FTClient.zip", "FactorTester-Client.zip"}:
        return "macos-app"
    if name == "vibe-trading-adapter.zip":
        return "adapter-archive"
    raise ValueError(f"unsupported release asset: {name}")


def _assert_key_pair(private_key: Path, public_key: Path) -> None:
    result = subprocess.run(
        ["openssl", "ec", "-in", str(private_key), "-pubout"],
        check=True,
        capture_output=True,
    )
    if result.stdout != public_key.read_bytes():
        raise ValueError("release private key does not match trusted public key")


def _sign(payload: bytes, private_key: Path) -> bytes:
    with tempfile.TemporaryDirectory(prefix="factortester-sign-") as raw:
        root = Path(raw)
        source = root / "manifest.json"
        signature = root / "manifest.sig"
        source.write_bytes(payload)
        subprocess.run(
            [
                "openssl",
                "dgst",
                "-sha256",
                "-sign",
                str(private_key),
                "-out",
                str(signature),
                str(source),
            ],
            check=True,
            capture_output=True,
        )
        return signature.read_bytes()
