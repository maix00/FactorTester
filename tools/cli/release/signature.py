"""ECDSA/SHA-256 verification through the platform OpenSSL binary."""

from __future__ import annotations

import base64
from pathlib import Path
import shutil
import subprocess
import tempfile


def verify_ecdsa_sha256(
    payload: bytes,
    encoded_signature: str,
    *,
    public_key: Path,
) -> None:
    openssl = shutil.which("openssl")
    if not openssl:
        raise ValueError("release signature verification requires openssl")
    if not public_key.is_file():
        raise ValueError(f"release public key not found: {public_key}")
    try:
        signature = base64.b64decode(
            encoded_signature,
            validate=True,
        )
    except ValueError as exc:
        raise ValueError("release signature is not valid base64") from exc
    with tempfile.TemporaryDirectory(prefix="factortester-signature-") as raw:
        root = Path(raw)
        payload_path = root / "manifest.json"
        signature_path = root / "manifest.sig"
        payload_path.write_bytes(payload)
        signature_path.write_bytes(signature)
        result = subprocess.run(
            [
                openssl,
                "dgst",
                "-sha256",
                "-verify",
                str(public_key),
                "-signature",
                str(signature_path),
                str(payload_path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    if result.returncode != 0:
        raise ValueError("release manifest signature verification failed")
