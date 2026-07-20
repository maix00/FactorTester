from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import subprocess

import pytest

from script.release.update_manifest import (
    create_update_manifest,
    verify_installer,
    write_update_manifest,
)
from tools.cli.release.update_channel import (
    resolve_update_manifest,
    validate_update_manifest,
)


def _keys(root: Path) -> tuple[Path, Path]:
    root.mkdir(parents=True)
    private = root / "private.pem"
    public = root / "public.pem"
    subprocess.run(
        [
            "openssl", "genpkey", "-algorithm", "EC",
            "-pkeyopt", "ec_paramgen_curve:P-256", "-out", str(private),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "openssl", "pkey", "-in", str(private), "-pubout",
            "-out", str(public),
        ],
        check=True,
        capture_output=True,
    )
    return private, public


def _manifest(
    root: Path,
    *,
    channel: str = "stable",
) -> tuple[dict, Path, Path]:
    private, public = _keys(root / "keys")
    dmg = root / "FactorTester-Client.dmg"
    dmg.write_bytes(b"signed installer")
    manifest = create_update_manifest(
        version="1.2.3" if channel == "stable" else "1.3.0-beta.1",
        build=42,
        channel=channel,
        dmg=dmg,
        dmg_url=(
            "https://github.com/maix00/FactorTester-Client/releases/"
            "download/v1.2.3/FactorTester-Client.dmg"
        ),
        minimum_client="1.0.0",
        mandatory=False,
        published_at="2026-07-20T12:00:00Z",
        private_key=private,
        public_key=public,
    )
    return manifest, public, dmg


def test_update_manifest_is_compact_signed_and_verifies_installer(
    tmp_path: Path,
) -> None:
    manifest, public, dmg = _manifest(tmp_path)
    validated = validate_update_manifest(
        manifest, public_key=public, expected_channel="stable"
    )
    assert validated.version == "1.2.3"
    assert validated.build == 42
    assert validated.dmg_sha256 == manifest["sha256"]
    assert len(json.dumps(manifest)) < 4_000
    verify_installer(
        dmg, manifest, public_key=public, channel="stable"
    )
    path = write_update_manifest(tmp_path / "stable.json", manifest)
    assert path.read_text().endswith("\n")

    dmg.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="SHA256"):
        verify_installer(
            dmg, manifest, public_key=public, channel="stable"
        )


def test_server_failure_falls_back_only_to_signed_github_manifest(
    tmp_path: Path,
) -> None:
    manifest, public, _ = _manifest(tmp_path)
    trusted = json.dumps(manifest).encode()
    tampered = json.loads(trusted)
    tampered["build"] = 43
    responses = {
        "https://factor.example/api/client/releases/stable.json": (
            json.dumps(tampered).encode()
        ),
        "https://github.example/stable.json": trusted,
    }

    def opener(request, timeout):
        assert timeout == 15
        return BytesIO(responses[request.full_url])

    _, validated, source = resolve_update_manifest(
        server_manifest_url=(
            "https://factor.example/api/client/releases/stable.json"
        ),
        github_manifest_url="https://github.example/stable.json",
        channel="stable",
        public_key=public,
        opener=opener,
    )
    assert source == "github"
    assert validated.build == 42

    responses["https://github.example/stable.json"] = json.dumps(
        tampered
    ).encode()
    with pytest.raises(ValueError, match="no trusted"):
        resolve_update_manifest(
            server_manifest_url=(
                "https://factor.example/api/client/releases/stable.json"
            ),
            github_manifest_url="https://github.example/stable.json",
            channel="stable",
            public_key=public,
            opener=opener,
        )


def test_channel_and_minimum_client_are_signed_fields(tmp_path: Path) -> None:
    manifest, public, _ = _manifest(tmp_path)
    manifest["minimum_client"] = "9.0.0"
    with pytest.raises(ValueError, match="signature"):
        validate_update_manifest(manifest, public_key=public)
