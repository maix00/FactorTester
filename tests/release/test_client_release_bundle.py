from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import zipfile

import pytest

from tools.cli.release.client_release_bundle import (
    build_client_release_bundle,
    extract_client_release_bundle,
    inspect_client_release_bundle,
)


def _inputs(root: Path) -> tuple[Path, Path, Path]:
    dmg = root / "FTClient.dmg"
    dmg.write_bytes(b"installer bytes")
    digest = sha256(dmg.read_bytes()).hexdigest()
    manifest = root / "beta.json"
    manifest.write_text(json.dumps({
        "schema_version": 1,
        "version": "0.1.3-beta.33",
        "build": 36,
        "channel": "beta",
        "dmg_url": f"https://factor.example/api/client/releases/assets/beta/{digest}.dmg",
        "sha256": digest,
        "minimum_client": "0.1.0",
        "mandatory": False,
        "published_at": "2026-08-16T00:00:00Z",
        "signature": {"algorithm": "ecdsa-sha256", "key_id": "x", "value": "y"},
    }), encoding="utf-8")
    appcast = root / "beta.xml"
    appcast.write_text("<rss />", encoding="utf-8")
    return dmg, appcast, manifest


def test_release_bundle_is_content_addressed_and_extracts_safely(tmp_path: Path) -> None:
    dmg, appcast, manifest = _inputs(tmp_path)
    package = tmp_path / "release.zip"
    result = build_client_release_bundle(
        dmg=dmg,
        appcast=appcast,
        manifest=manifest,
        output=package,
    )

    assert result["version"] == "0.1.3-beta.33"
    assert result["build"] == 36
    inspected = inspect_client_release_bundle(package)
    assert inspected["package_sha256"] == sha256(package.read_bytes()).hexdigest()
    extracted = tmp_path / "extracted"
    extract_client_release_bundle(package, extracted)
    assert (extracted / "beta.json").read_bytes() == manifest.read_bytes()
    assert (extracted / "beta.xml").read_bytes() == appcast.read_bytes()


def test_release_bundle_rejects_path_traversal(tmp_path: Path) -> None:
    package = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("../beta.json", "{}")
    with pytest.raises(ValueError, match="member path"):
        inspect_client_release_bundle(package)
