"""One transactional command for building and publishing a local Beta release."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
from uuid import uuid4

from script.release.assets import build_installer_dmg, embed_client_runtime
from script.release.build import (
    REPO, _sign_embedded_app, _validate_source_checkout,
)
from script.release.update_manifest import (
    create_update_manifest, verify_installer, write_update_manifest,
)

DEFAULT_IDENTITY = "FTClient Beta Release"


def publish_beta_files(
    *,
    dmg: Path,
    manifest: dict,
    release_root: Path,
) -> tuple[Path, Path]:
    """Publish immutable asset first and atomically replace beta.json last."""
    digest = sha256(dmg.read_bytes()).hexdigest()
    asset = release_root / "assets" / "beta" / f"{digest}.dmg"
    asset.parent.mkdir(parents=True, exist_ok=True)
    if asset.exists():
        if sha256(asset.read_bytes()).hexdigest() != digest:
            raise ValueError("existing digest-addressed beta asset is corrupt")
    else:
        temporary = asset.with_name(f".{asset.name}.staging-{uuid4().hex}")
        shutil.copy2(dmg, temporary)
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        temporary.rename(asset)
    manifest_path = release_root / "beta.json"
    temporary_manifest = manifest_path.with_name(
        f".{manifest_path.name}.staging-{uuid4().hex}"
    )
    write_update_manifest(temporary_manifest, manifest)
    with temporary_manifest.open("rb") as stream:
        os.fsync(stream.fileno())
    temporary_manifest.replace(manifest_path)
    return asset, manifest_path


def release_beta(
    *,
    version: str,
    source_revision: str,
    build: int,
    server_origin: str,
    release_root: Path,
    private_key: Path,
    public_key: Path,
    output: Path,
    cache_dir: Path,
    signing_identity: str = DEFAULT_IDENTITY,
    minimum_client: str = "0.1.0",
    mandatory: bool = False,
) -> dict:
    if not signing_identity.strip() or signing_identity.strip() == "-":
        raise ValueError("ad-hoc signing is forbidden")
    _validate_source_checkout(REPO, source_revision)
    if output.exists():
        raise ValueError(f"release output already exists: {output}")
    output.mkdir(parents=True)
    subprocess.run(
        ["xcodegen", "generate", "--spec", str(REPO / "apple/project.yml"),
         "--project", str(REPO / "apple")],
        check=True,
    )
    subprocess.run(
        ["xcodebuild", "-project", str(REPO / "apple/FactorTester-Client.xcodeproj"),
         "-scheme", "FactorTester-Client-macOS", "-configuration", "Release",
         "-derivedDataPath", str(REPO / "apple/build"),
         "CODE_SIGNING_ALLOWED=NO", "build"],
        check=True,
    )
    source = REPO / "apple/build/Build/Products/Release/FTClient.app"
    with (source / "Contents/Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    if info.get("CFBundleShortVersionString") != version:
        raise ValueError("release version does not match the macOS app")
    if str(info.get("CFBundleVersion")) != str(build):
        raise ValueError("release build does not match the macOS app")
    staged = output / ".staging" / "FTClient.app"
    shutil.copytree(source, staged)
    embed_client_runtime(
        REPO, staged, version=f"bundle-b{build}-r{source_revision}",
        source_revision=source_revision, cache_dir=cache_dir,
    )
    _sign_embedded_app(staged, signing_identity)
    dmg = build_installer_dmg(staged, output / "FactorTester-Client.dmg")
    digest = sha256(dmg.read_bytes()).hexdigest()
    url = (
        server_origin.rstrip("/")
        + f"/api/client/releases/assets/beta/{digest}.dmg"
    )
    manifest = create_update_manifest(
        version=version, build=build, channel="beta", dmg=dmg, dmg_url=url,
        minimum_client=minimum_client, mandatory=mandatory,
        published_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        private_key=private_key, public_key=public_key,
    )
    verify_installer(dmg, manifest, public_key=public_key, channel="beta")
    asset, manifest_path = publish_beta_files(
        dmg=dmg, manifest=manifest, release_root=release_root,
    )
    shutil.rmtree(output / ".staging")
    receipt = {
        "schema_version": 1, "version": version, "build": build,
        "source_revision": source_revision, "dmg_sha256": digest,
        "asset": str(asset), "manifest": str(manifest_path),
    }
    (output / "release-receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    )
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--build", required=True, type=int)
    parser.add_argument("--server-origin", required=True)
    parser.add_argument("--release-root", required=True, type=Path)
    parser.add_argument("--private-key", required=True, type=Path)
    parser.add_argument("--public-key", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cache-dir", type=Path, default=(
        Path.home() / "Library/Caches/FactorTester/release-runtime"
    ))
    parser.add_argument("--signing-identity", default=DEFAULT_IDENTITY)
    parser.add_argument("--minimum-client", default="0.1.0")
    parser.add_argument("--mandatory", action="store_true")
    args = vars(parser.parse_args())
    print(json.dumps(release_beta(**args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
