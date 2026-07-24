"""One public Main/Beta release entry point.

The publisher deliberately keeps transport authority out of the client update
code. Beta is committed to the server's shared release directory; Main is
uploaded as one draft GitHub Release and becomes visible only after every
artifact has been uploaded.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4

from script.release.assets import build_installer_dmg, embed_client_runtime
from script.release.build import REPO, _sign_embedded_app, _validate_source_checkout
from script.release.sparkle import (
    generate_sparkle_appcast,
    validate_sparkle_appcast,
)
from script.release.update_manifest import (
    create_update_manifest,
    verify_installer,
    write_update_manifest,
)


CHANNELS = {"stable", "beta"}
SHARED_SIGNING_IDENTITY = "FTClient Beta Release"
SHARED_SIGNING_CERTIFICATE_SHA1 = "E6F25D4B158C8FA4AE585E9C374AE9FAC7AFC81A"


@dataclass(frozen=True)
class PublishedRelease:
    channel: str
    version: str
    build: int
    source_revision: str
    dmg_sha256: str
    signing_certificate_sha1: str
    asset_url: str
    appcast_url: str
    legacy_manifest_url: str


def release_client(
    *,
    channel: str,
    version: str,
    build: int,
    source_revision: str,
    output: Path,
    signing_identity: str,
    sparkle_public_key: str,
    sparkle_generate_appcast: Path,
    legacy_private_key: Path,
    legacy_public_key: Path,
    server_origin: str | None = None,
    release_root: Path | None = None,
    github_repository: str = "maix00/FactorTester-Client",
    cache_dir: Path | None = None,
    minimum_client: str = "0.1.0",
    mandatory: bool = False,
    notary_profile: str | None = None,
) -> PublishedRelease:
    """Build, sign, optionally notarize, publish, and read back one release."""
    if channel not in CHANNELS:
        raise ValueError("release channel must be stable or beta")
    if not sparkle_public_key.strip():
        raise ValueError("Sparkle public key is required")
    if signing_identity != SHARED_SIGNING_IDENTITY:
        raise ValueError(
            "Main and Beta must use the existing shared FTClient signing "
            "identity"
        )
    signing_identity = _shared_signing_certificate()
    if channel == "beta" and (server_origin is None or release_root is None):
        raise ValueError("Beta requires server origin and release root")
    _validate_source_checkout(REPO, source_revision)
    if output.exists():
        raise ValueError(f"release output already exists: {output}")
    output.mkdir(parents=True)
    staging = output / ".staging"
    try:
        subprocess.run(
            [
                "xcodegen", "generate",
                "--spec", str(REPO / "apple/project.yml"),
                "--project", str(REPO / "apple"),
            ],
            check=True,
        )
        subprocess.run(
            [
                "xcodebuild",
                "-project", str(REPO / "apple/FactorTester-Client.xcodeproj"),
                "-scheme", "FactorTester-Client-macOS",
                "-configuration", "Release",
                "-derivedDataPath", str(REPO / "apple/build"),
                f"MARKETING_VERSION={version}",
                f"CURRENT_PROJECT_VERSION={build}",
                f"SPARKLE_PUBLIC_ED_KEY={sparkle_public_key}",
                "CODE_SIGNING_ALLOWED=NO",
                "build",
            ],
            check=True,
        )
        source = REPO / "apple/build/Build/Products/Release/FTClient.app"
        app = staging / "FTClient.app"
        shutil.copytree(source, app)
        embed_client_runtime(
            REPO,
            app,
            version=f"bundle-b{build}-r{source_revision}",
            source_revision=source_revision,
            cache_dir=cache_dir,
        )
        _sign_embedded_app(app, signing_identity)
        if notary_profile:
            _notarize_app(app, notary_profile)
        dmg = build_installer_dmg(app, output / "FactorTester-Client.dmg")
        if notary_profile:
            _notarize_dmg(dmg, notary_profile)
        digest = sha256(dmg.read_bytes()).hexdigest()
        if channel == "beta":
            origin = str(server_origin).rstrip("/")
            download_url = (
                f"{origin}/api/client/releases/assets/beta/{digest}.dmg"
            )
            appcast_url = f"{origin}/api/client/releases/beta.xml"
            legacy_url = f"{origin}/api/client/releases/beta.json"
        else:
            base = (
                f"https://github.com/{github_repository}"
                "/releases/latest/download"
            )
            download_url = f"{base}/FactorTester-Client.dmg"
            appcast_url = f"{base}/appcast.xml"
            legacy_url = f"{base}/stable.json"

        appcast = output / "appcast.xml"
        generate_sparkle_appcast(
            archive=dmg,
            output=appcast,
            tool=sparkle_generate_appcast,
            download_url=download_url,
            version=version,
            build=build,
            channel=channel,
        )
        manifest = create_update_manifest(
            version=version,
            build=build,
            channel=channel,
            dmg=dmg,
            dmg_url=download_url,
            minimum_client=minimum_client,
            mandatory=mandatory,
            published_at=_published_at(),
            private_key=legacy_private_key,
            public_key=legacy_public_key,
        )
        verify_installer(
            dmg,
            manifest,
            public_key=legacy_public_key,
            channel=channel,
        )
        legacy_path = write_update_manifest(
            output / f"{channel}.json",
            manifest,
        )

        if channel == "beta":
            publish_beta_directory(
                dmg=dmg,
                appcast=appcast,
                legacy_manifest=manifest,
                release_root=release_root,  # type: ignore[arg-type]
            )
        else:
            publish_main_github(
                repository=github_repository,
                tag=f"client-v{version}-b{build}",
                title=f"FTClient {version} ({build})",
                dmg=dmg,
                appcast=appcast,
                legacy_manifest_path=legacy_path,
            )

        for url, expected in (
            (download_url, dmg),
            (appcast_url, appcast),
            (legacy_url, legacy_path),
        ):
            verify_remote_bytes(url, expected)
        receipt = PublishedRelease(
            channel=channel,
            version=version,
            build=build,
            source_revision=source_revision,
            dmg_sha256=digest,
            signing_certificate_sha1=SHARED_SIGNING_CERTIFICATE_SHA1,
            asset_url=download_url,
            appcast_url=appcast_url,
            legacy_manifest_url=legacy_url,
        )
        write_release_receipt(output / "release-receipt.json", receipt)
        return receipt
    except Exception:
        # A draft GitHub release remains non-public on upload failure and Beta
        # channel pointers are switched only after immutable payloads exist.
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def publish_beta_directory(
    *,
    dmg: Path,
    appcast: Path,
    legacy_manifest: dict,
    release_root: Path,
) -> tuple[Path, Path, Path]:
    """Commit immutable payloads first, then switch both channel pointers."""
    digest = sha256(dmg.read_bytes()).hexdigest()
    asset = release_root / "assets" / "beta" / f"{digest}.dmg"
    asset.parent.mkdir(parents=True, exist_ok=True)
    _copy_immutable(dmg, asset, expected_sha256=digest)

    versioned_appcast = (
        release_root / "appcasts" / "beta" / f"{digest}.xml"
    )
    versioned_appcast.parent.mkdir(parents=True, exist_ok=True)
    _copy_immutable(appcast, versioned_appcast)

    appcast_pointer = release_root / "beta.xml"
    legacy_pointer = release_root / "beta.json"
    staged_appcast = _stage_copy(versioned_appcast, appcast_pointer)
    staged_legacy = legacy_pointer.with_name(
        f".{legacy_pointer.name}.staging-{uuid4().hex}"
    )
    write_update_manifest(staged_legacy, legacy_manifest)
    _fsync(staged_legacy)

    # Old clients keep reading beta.json for one compatibility window. Publish
    # it first; new Sparkle clients switch immediately afterwards.
    staged_legacy.replace(legacy_pointer)
    staged_appcast.replace(appcast_pointer)
    return asset, appcast_pointer, legacy_pointer


def publish_main_github(
    *,
    repository: str,
    tag: str,
    title: str,
    dmg: Path,
    appcast: Path,
    legacy_manifest_path: Path,
    prerelease: bool = False,
) -> None:
    """Upload a complete draft release before exposing its channel pointers."""
    command = [
        "gh", "release", "create", tag,
        "--repo", repository,
        "--title", title,
        "--draft",
        str(dmg),
        f"{appcast}#appcast.xml",
        f"{legacy_manifest_path}#stable.json",
    ]
    subprocess.run(command, check=True)
    edit = [
        "gh", "release", "edit", tag,
        "--repo", repository,
        "--draft=false",
        "--latest",
    ]
    if prerelease:
        edit.extend(["--prerelease", "--latest=false"])
    subprocess.run(edit, check=True)


def verify_remote_bytes(url: str, expected: Path) -> None:
    """Read a published artifact back and compare its complete byte stream."""
    observed = subprocess.run(
        ["curl", "--fail", "--location", "--silent", "--show-error", url],
        check=True,
        capture_output=True,
    ).stdout
    if sha256(observed).digest() != sha256(expected.read_bytes()).digest():
        raise ValueError(f"published artifact readback failed: {url}")


def write_release_receipt(
    path: Path,
    receipt: PublishedRelease,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.staging-{uuid4().hex}")
    temporary.write_text(
        json.dumps(
            {"schema_version": 1, **asdict(receipt)},
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    _fsync(temporary)
    temporary.replace(path)
    return path


def validate_release_inputs(
    *,
    channel: str,
    version: str,
    build: int,
    source_revision: str,
    dmg: Path,
    appcast: Path,
    download_url: str,
) -> None:
    if channel not in CHANNELS:
        raise ValueError("release channel must be stable or beta")
    if build < 1:
        raise ValueError("release build must be positive")
    if len(source_revision) != 40 or any(
        character not in "0123456789abcdef"
        for character in source_revision
    ):
        raise ValueError("source revision must be a full lowercase Git SHA")
    if not dmg.is_file():
        raise ValueError("release DMG does not exist")
    validate_sparkle_appcast(
        appcast,
        version=version,
        build=build,
        channel=channel,
        download_url=download_url,
    )


def _copy_immutable(
    source: Path,
    destination: Path,
    *,
    expected_sha256: str | None = None,
) -> None:
    expected = expected_sha256 or sha256(source.read_bytes()).hexdigest()
    if destination.exists():
        if sha256(destination.read_bytes()).hexdigest() != expected:
            raise ValueError(f"immutable release artifact is corrupt: {destination}")
        return
    temporary = destination.with_name(
        f".{destination.name}.staging-{uuid4().hex}"
    )
    shutil.copy2(source, temporary)
    _fsync(temporary)
    temporary.rename(destination)


def _stage_copy(source: Path, pointer: Path) -> Path:
    temporary = pointer.with_name(
        f".{pointer.name}.staging-{uuid4().hex}"
    )
    shutil.copy2(source, temporary)
    _fsync(temporary)
    return temporary


def _fsync(path: Path) -> None:
    with path.open("rb") as stream:
        os.fsync(stream.fileno())


def _shared_signing_certificate() -> str:
    output = subprocess.check_output(
        ["security", "find-identity", "-v", "-p", "codesigning"],
        text=True,
    )
    matches = [
        line.split()[1].upper()
        for line in output.splitlines()
        if f'"{SHARED_SIGNING_IDENTITY}"' in line
    ]
    if matches != [SHARED_SIGNING_CERTIFICATE_SHA1]:
        raise ValueError(
            "the Keychain does not contain exactly the pinned FTClient "
            "signing certificate"
        )
    return SHARED_SIGNING_CERTIFICATE_SHA1


def _notarize_app(app: Path, profile: str) -> None:
    archive = app.with_suffix(".zip")
    subprocess.run(
        [
            "ditto", "-c", "-k", "--keepParent",
            "--sequesterRsrc", str(app), str(archive),
        ],
        check=True,
    )
    subprocess.run(
        [
            "xcrun", "notarytool", "submit", str(archive),
            "--keychain-profile", profile,
            "--wait",
        ],
        check=True,
    )
    subprocess.run(["xcrun", "stapler", "staple", str(app)], check=True)
    archive.unlink()


def _notarize_dmg(dmg: Path, profile: str) -> None:
    subprocess.run(
        [
            "xcrun", "notarytool", "submit", str(dmg),
            "--keychain-profile", profile,
            "--wait",
        ],
        check=True,
    )
    subprocess.run(["xcrun", "stapler", "staple", str(dmg)], check=True)
    subprocess.run(["xcrun", "stapler", "validate", str(dmg)], check=True)


def _published_at() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build and publish one verified FTClient Main or Beta release"
    )
    parser.add_argument("--channel", choices=sorted(CHANNELS), required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--build", type=int, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--signing-identity",
        default=SHARED_SIGNING_IDENTITY,
    )
    parser.add_argument("--sparkle-public-key", required=True)
    parser.add_argument("--sparkle-generate-appcast", type=Path, required=True)
    parser.add_argument("--legacy-private-key", type=Path, required=True)
    parser.add_argument("--legacy-public-key", type=Path, required=True)
    parser.add_argument("--server-origin")
    parser.add_argument("--release-root", type=Path)
    parser.add_argument(
        "--github-repository",
        default="maix00/FactorTester-Client",
    )
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--minimum-client", default="0.1.0")
    parser.add_argument("--mandatory", action="store_true")
    parser.add_argument("--notary-profile")
    args = parser.parse_args()
    receipt = release_client(**vars(args))
    print(json.dumps(asdict(receipt), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
