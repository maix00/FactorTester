"""One public Main/Beta release entry point.

The publisher deliberately keeps transport authority out of the client update
code. Beta is committed to the server's shared release directory; Main is
uploaded as one draft GitHub Release and becomes visible only after every
artifact has been uploaded.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

# Keep the public script entry point usable when invoked as
# ``python scripts/release/publish.py``.  In that mode Python initially puts
# ``scripts/release`` on sys.path, which would otherwise make both the release
# package unavailable before argparse can run.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.release.assets import build_installer_dmg, embed_client_runtime
from scripts.release.build import (
    REPO,
    _sign_embedded_app,
    _validate_source_checkout,
    discard_xcode_app,
    prepare_xcode_build_root,
    validate_embedded_sparkle_key,
    xcodebuild_environment,
)
from scripts.release.package_layout import validate_client_package_layout
from scripts.release.source_checkout import clean_worktree
from scripts.release.sparkle import (
    generate_sparkle_appcast,
    validate_sparkle_appcast,
)
from scripts.release.update_manifest import (
    create_update_manifest,
    verify_installer,
    write_update_manifest,
)
from tools.cli.release.beta_version import (
    read_installed_beta_release,
    resolve_beta_identity,
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
    delta_only: bool = False
    source_mode: str = "current-checkout"


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
    previous_archive: Path | None = None,
    previous_appcast: Path | None = None,
    delta_only: bool = False,
    from_clean_commit: str | None = None,
) -> PublishedRelease:
    """Build, sign, optionally notarize, publish, and read back one release."""
    if from_clean_commit is not None:
        if from_clean_commit != source_revision:
            raise ValueError(
                "--from-clean-commit must equal --source-revision"
            )
        with clean_worktree(REPO, from_clean_commit) as checkout:
            original_repo = globals()["REPO"]
            from scripts.release import build as release_build
            original_build_repo = release_build.REPO
            globals()["REPO"] = checkout
            release_build.REPO = checkout
            try:
                receipt = release_client(
                    channel=channel,
                    version=version,
                    build=build,
                    source_revision=source_revision,
                    output=output,
                    signing_identity=signing_identity,
                    sparkle_public_key=sparkle_public_key,
                    sparkle_generate_appcast=sparkle_generate_appcast,
                    legacy_private_key=legacy_private_key,
                    legacy_public_key=legacy_public_key,
                    server_origin=server_origin,
                    release_root=release_root,
                    github_repository=github_repository,
                    cache_dir=cache_dir,
                    minimum_client=minimum_client,
                    mandatory=mandatory,
                    notary_profile=notary_profile,
                    previous_archive=previous_archive,
                    previous_appcast=previous_appcast,
                    delta_only=delta_only,
                )
            finally:
                globals()["REPO"] = original_repo
                release_build.REPO = original_build_repo
        return _persist_clean_commit_receipt(output, receipt)
    if channel not in CHANNELS:
        raise ValueError("release channel must be stable or beta")
    if delta_only and channel != "beta":
        raise ValueError("Delta-only publishing is supported only for Beta")
    if delta_only and not _is_loopback_release_origin(server_origin):
        raise ValueError(
            "Delta-only publishing with the local release identity is restricted "
            "to a loopback Beta server"
        )
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
    _validate_legacy_release_key(channel, legacy_public_key)
    _validate_legacy_release_key_pair(
        legacy_private_key,
        legacy_public_key,
    )
    _validate_release_trust_root_copies(REPO)
    _validate_source_checkout(REPO, source_revision)
    validate_client_package_layout(REPO)
    build_environment = xcodebuild_environment()
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
        build_root = REPO / "apple/build"
        source = build_root / "Build/Products/Release/FTClient.app"
        prepare_xcode_build_root(build_root)
        try:
            subprocess.run(
                [
                    "xcodebuild",
                    "-project", str(REPO / "apple/FactorTester-Client.xcodeproj"),
                    "-scheme", "FactorTester-Client-macOS",
                    "-configuration", "Release",
                    "-derivedDataPath", str(build_root),
                    f"MARKETING_VERSION={version}",
                    f"CURRENT_PROJECT_VERSION={build}",
                    f"SPARKLE_PUBLIC_ED_KEY={sparkle_public_key}",
                    "CODE_SIGNING_ALLOWED=NO",
                    "build",
                ],
                env=build_environment,
                check=True,
            )
            app = staging / "FTClient.app"
            shutil.copytree(source, app, symlinks=True)
        finally:
            discard_xcode_app(source)
        validate_embedded_sparkle_key(app, expected=sparkle_public_key)
        _validate_embedded_release_trust_root(
            app,
            channel=channel,
            expected=legacy_public_key,
        )
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

        if channel == "beta" and previous_archive is None:
            previous = _discover_previous_beta_release(release_root)
            if previous is not None:
                previous_archive, previous_archive_url, previous_appcast = previous
            else:
                previous_archive_url = None
        elif previous_archive is not None:
            previous_archive_url = None
        else:
            previous_archive_url = None
        delta_output = output / "deltas"

        appcast = output / "appcast.xml"
        generated_appcast = generate_sparkle_appcast(
            archive=dmg,
            output=appcast,
            tool=sparkle_generate_appcast,
            download_url=download_url,
            version=version,
            build=build,
            channel=channel,
            previous_archive=previous_archive,
            previous_archive_url=previous_archive_url,
        previous_appcast=previous_appcast,
        delta_output=delta_output,
        delta_only=delta_only,
        latest_only=channel == "beta",
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

        beta_publication = None
        if channel == "beta":
            beta_publication = publish_beta_directory(
                dmg=dmg,
                appcast=appcast,
                legacy_manifest=manifest,
                release_root=release_root,  # type: ignore[arg-type]
                deltas=generated_appcast.delta_paths,
                publish_full=not delta_only,
                retain_base=delta_only,
            )
        else:
            publish_main_github(
                repository=github_repository,
                tag=f"client-v{version}-b{build}",
                title=f"FTClient {version} ({build})",
                dmg=dmg,
                appcast=appcast,
                legacy_manifest_path=legacy_path,
                deltas=generated_appcast.delta_paths,
            )

        readbacks = [
            (appcast_url, appcast),
            (legacy_url, legacy_path),
        ]
        if not delta_only:
            readbacks.insert(0, (download_url, dmg))
        for url, expected in readbacks:
            verify_remote_bytes(url, expected)
        delta_prefix = download_url.rsplit("/", 1)[0] + "/"
        for delta in generated_appcast.delta_paths:
            verify_remote_bytes(delta_prefix + delta.name, delta)
        if beta_publication is not None:
            beta_publication.finalize()
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
            delta_only=delta_only,
            source_mode="current-checkout",
        )
        write_release_receipt(output / "release-receipt.json", receipt)
        # Delta-only Beta releases use the full DMG only as a transient input
        # for signing, installer verification, and Sparkle delta generation.
        # The previous release remains the durable base archive on the server;
        # retaining this newly built DMG locally would waste disk space and
        # falsely suggest that it is available for first-install fallback.
        if delta_only:
            _remove_local_archive(dmg)
        return receipt
    except Exception:
        if "beta_publication" in locals() and beta_publication is not None:
            beta_publication.rollback()
        # A draft GitHub release remains non-public on upload failure and Beta
        # channel pointers are switched only after immutable payloads exist.
        # The output directory belongs to this invocation because pre-existing
        # destinations are rejected above.  Do not leave an empty or partial
        # release that can be mistaken for a completed build.
        shutil.rmtree(output, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _is_loopback_release_origin(value: str | None) -> bool:
    split = urlsplit(str(value or ""))
    if split.scheme not in {"http", "https"} or not split.hostname:
        return False
    if split.username or split.password or split.query or split.fragment:
        return False
    if split.hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(split.hostname).is_loopback
    except ValueError:
        return False


def publish_release(**options: Any) -> PublishedRelease:
    """Build and publish a client without touching any FactorTester server.

    Client packaging and server deployment have different lifecycle owners.
    In particular, a Docker-managed internal Manager must not be stopped or
    restarted merely because FTClient is being built.  Server source/image
    rollout remains an explicit Docker/deployment operation outside this
    client release transaction.
    """
    source_revision = str(options.get("source_revision") or "")
    # A clean-commit release deliberately builds from a temporary detached
    # worktree.  Do not reject the caller's checkout before that worktree is
    # materialized; normal current-checkout releases remain strict.
    clean_revision = str(options.get("from_clean_commit") or "").strip()
    if clean_revision:
        if clean_revision != source_revision:
            raise ValueError(
                "--from-clean-commit must equal --source-revision"
            )
        subprocess.run(
            ["git", "cat-file", "-e", f"{clean_revision}^{{commit}}"],
            cwd=REPO,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        _validate_source_checkout(REPO, source_revision)
    channel = str(options.get("channel") or "").strip()
    if channel == "beta":
        sources: list[str | Path] = []
        release_root = options.get("release_root")
        if release_root is not None:
            sources.append(Path(release_root))
        server_origin = str(options.get("server_origin") or "").strip()
        if server_origin:
            sources.append(server_origin)
        installed_release = read_installed_beta_release(
            Path("/Applications/FTClient.app/Contents/Info.plist"),
        )
        if installed_release is not None:
            sources.append(Path(installed_release.source))
        version, build, _discovered = resolve_beta_identity(
            version=options.get("version"),
            build=options.get("build"),
            sources=sources,
            project_file=REPO / "apple/project.yml",
            ca_file=options.get("server_ca_file"),
        )
        options["version"] = version
        options["build"] = build
    elif (
        not str(options.get("version") or "").strip()
        or str(options.get("version") or "").strip().lower() == "auto"
    ):
        raise ValueError("Stable release requires an explicit --version")
    elif str(options.get("build") or "").strip().lower() == "auto":
        raise ValueError("Stable release requires an explicit --build")
    options.pop("server_ca_file", None)
    return release_client(**options)


def _persist_clean_commit_receipt(
    output: Path,
    receipt: PublishedRelease,
) -> PublishedRelease:
    clean_receipt = PublishedRelease(
        **{**asdict(receipt), "source_mode": "clean-commit"}
    )
    write_release_receipt(output / "release-receipt.json", clean_receipt)
    return clean_receipt


@dataclass
class BetaPublication:
    release_root: Path
    digest: str
    delta_names: frozenset[str]
    retain_base: bool
    previous_appcast: bytes | None
    previous_legacy: bytes | None
    created_paths: tuple[Path, ...]

    def finalize(self) -> None:
        if self.retain_base:
            _prune_beta_bases(self.release_root, keep=self.digest)
        else:
            _prune_beta_bases(self.release_root, keep="")
        _prune_beta_public_artifacts(
            self.release_root,
            keep_digest=self.digest,
            keep_deltas=set(self.delta_names),
        )

    def rollback(self) -> None:
        _restore_pointer(
            self.release_root / "beta.xml",
            self.previous_appcast,
        )
        _restore_pointer(
            self.release_root / "beta.json",
            self.previous_legacy,
        )
        for path in self.created_paths:
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def publish_beta_directory(
    *,
    dmg: Path,
    appcast: Path,
    legacy_manifest: dict,
    release_root: Path,
    deltas: tuple[Path, ...] = (),
    publish_full: bool = True,
    retain_base: bool = False,
) -> BetaPublication:
    """Commit immutable payloads first, then switch both channel pointers."""
    existing_paths = {
        path.resolve()
        for path in release_root.rglob("*")
        if path.is_file()
    }
    digest = sha256(dmg.read_bytes()).hexdigest()
    asset = release_root / "assets" / "beta" / f"{digest}.dmg"
    asset.parent.mkdir(parents=True, exist_ok=True)
    if publish_full:
        _copy_immutable(dmg, asset, expected_sha256=digest)
    if retain_base:
        base = release_root / "bases" / "beta" / f"{digest}.dmg"
        base.parent.mkdir(parents=True, exist_ok=True)
        _copy_immutable(dmg, base, expected_sha256=digest)
    for delta in deltas:
        _copy_immutable(
            delta,
            release_root / "assets" / "beta" / delta.name,
        )

    versioned_appcast = (
        release_root / "appcasts" / "beta" / f"{digest}.xml"
    )
    versioned_appcast.parent.mkdir(parents=True, exist_ok=True)
    _copy_immutable(appcast, versioned_appcast)

    appcast_pointer = release_root / "beta.xml"
    legacy_pointer = release_root / "beta.json"
    previous_appcast = (
        appcast_pointer.read_bytes() if appcast_pointer.is_file() else None
    )
    previous_legacy = (
        legacy_pointer.read_bytes() if legacy_pointer.is_file() else None
    )
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
    created_paths = tuple(
        path
        for path in release_root.rglob("*")
        if path.is_file()
        and path.resolve() not in existing_paths
        and path not in {appcast_pointer, legacy_pointer}
    )
    return BetaPublication(
        release_root=release_root,
        digest=digest,
        delta_names=frozenset(delta.name for delta in deltas),
        retain_base=retain_base,
        previous_appcast=previous_appcast,
        previous_legacy=previous_legacy,
        created_paths=created_paths,
    )


def _restore_pointer(path: Path, value: bytes | None) -> None:
    if value is None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    temporary = path.with_name(f".{path.name}.rollback-{uuid4().hex}")
    temporary.write_bytes(value)
    _fsync(temporary)
    temporary.replace(path)


def _validate_legacy_release_key(channel: str, public_key: Path) -> None:
    key_name = (
        "trusted-beta-release-public.pem"
        if channel == "beta"
        else "trusted-release-public.pem"
    )
    trusted = REPO / "tools/cli/release" / key_name
    if public_key.read_bytes() != trusted.read_bytes():
        raise ValueError(
            f"{channel} manifest public key does not match the client and "
            "server trust root"
        )


def _validate_legacy_release_key_pair(
    private_key: Path,
    public_key: Path,
) -> None:
    """Reject an incomplete key rotation before starting an expensive build."""
    try:
        result = subprocess.run(
            [
                "openssl", "pkey", "-in", str(private_key), "-pubout",
            ],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("release manifest private key is unreadable") from exc
    if result.stdout != public_key.read_bytes():
        raise ValueError(
            "release manifest private key does not match the trusted public key"
        )


def _validate_release_trust_root_copies(repo: Path) -> None:
    for key_name in (
        "trusted-beta-release-public.pem",
        "trusted-release-public.pem",
    ):
        cli_key = repo / "tools/cli/release" / key_name
        app_key = repo / "apple/Resources/Shared" / key_name
        if cli_key.read_bytes() != app_key.read_bytes():
            raise ValueError(
                f"{key_name} differs between the CLI and Apple resources"
            )


def _validate_embedded_release_trust_root(
    app: Path,
    *,
    channel: str,
    expected: Path,
) -> None:
    key_name = (
        "trusted-beta-release-public.pem"
        if channel == "beta"
        else "trusted-release-public.pem"
    )
    embedded = app / "Contents/Resources" / key_name
    if embedded.read_bytes() != expected.read_bytes():
        raise ValueError(
            f"release app embeds a different {channel} manifest trust root"
        )


def _prune_beta_bases(release_root: Path, *, keep: str) -> None:
    """Keep one private full archive as the next delta-generation base."""
    base_root = release_root / "bases" / "beta"
    for candidate in base_root.glob("*.dmg"):
        if candidate.stem != keep:
            candidate.unlink()


def _prune_beta_public_artifacts(
    release_root: Path,
    *,
    keep_digest: str,
    keep_deltas: set[str],
) -> None:
    """Remove public Beta artifacts no longer reachable from Delta-only mode."""
    assets = release_root / "assets" / "beta"
    for candidate in assets.glob("*.dmg"):
        if candidate.stem != keep_digest:
            candidate.unlink()
    for candidate in assets.glob("*.delta"):
        if candidate.name not in keep_deltas:
            candidate.unlink()

    appcasts = release_root / "appcasts" / "beta"
    current = appcasts / f"{keep_digest}.xml"
    for candidate in appcasts.glob("*.xml"):
        if candidate != current:
            candidate.unlink()


def _remove_local_archive(path: Path) -> None:
    """Remove a transient Delta-only full archive after successful publish."""
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _discover_previous_beta_release(
    release_root: Path | None,
) -> tuple[Path, str, Path | None] | None:
    if release_root is None:
        return None
    manifest_path = release_root / "beta.json"
    if not manifest_path.is_file():
        return None
    try:
        manifest: dict[str, Any] = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("previous Beta manifest is invalid") from exc
    digest = str(manifest.get("sha256") or "")
    archive_url = str(manifest.get("dmg_url") or "")
    if not digest or not archive_url:
        raise ValueError("previous Beta manifest lacks archive identity")
    archive = release_root / "assets" / "beta" / f"{digest}.dmg"
    if not archive.is_file():
        archive = release_root / "bases" / "beta" / f"{digest}.dmg"
    if not archive.is_file():
        raise ValueError("previous Beta archive is missing")
    appcast = release_root / "beta.xml"
    return archive, archive_url, appcast if appcast.is_file() else None


def publish_main_github(
    *,
    repository: str,
    tag: str,
    title: str,
    dmg: Path,
    appcast: Path,
    legacy_manifest_path: Path,
    deltas: tuple[Path, ...] = (),
    prerelease: bool = False,
) -> None:
    """Upload a complete draft release before exposing its channel pointers."""
    command = [
        "gh", "release", "create", tag,
        "--repo", repository,
        "--title", title,
        "--draft",
        str(dmg),
        *(str(delta) for delta in deltas),
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
    parser.add_argument(
        "--version",
        default="auto",
        help="Beta defaults to the next version from reachable Beta manifests.",
    )
    parser.add_argument(
        "--build",
        default="auto",
        help="Beta defaults to the next build from reachable Beta manifests.",
    )
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
    parser.add_argument("--server-ca-file", type=Path)
    parser.add_argument("--release-root", type=Path)
    parser.add_argument(
        "--github-repository",
        default="maix00/FactorTester-Client",
    )
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--minimum-client", default="0.1.0")
    parser.add_argument("--mandatory", action="store_true")
    parser.add_argument("--notary-profile")
    parser.add_argument(
        "--delta-only",
        action="store_true",
        help="Beta-only: publish only the delta from the previous version.",
    )
    parser.add_argument(
        "--previous-archive",
        type=Path,
        help="Previous app archive used to create a Sparkle delta.",
    )
    parser.add_argument(
        "--previous-appcast",
        type=Path,
        help="Previous appcast used to create a Sparkle delta.",
    )
    parser.add_argument(
        "--from-clean-commit",
        help=(
            "Explicitly build from this clean commit in a temporary worktree; "
            "must equal --source-revision."
        ),
    )
    args = parser.parse_args()
    options = vars(args)
    receipt = publish_release(**options)
    print(json.dumps(asdict(receipt), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
