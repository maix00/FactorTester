"""Assemble one signed, offline-installable FactorTester client release."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess

from script.release.assets import (
    embed_client_runtime,
    build_installer_dmg,
    refresh_runtime_receipt,
)


REPO = Path(__file__).resolve().parents[2]
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_LSREGISTER = Path(
    "/System/Library/Frameworks/CoreServices.framework/Versions/Current/"
    "Frameworks/LaunchServices.framework/Versions/Current/Support/lsregister"
)


def prepare_xcode_build_root(root: Path) -> None:
    """Keep transient Xcode products out of Spotlight results."""
    root.mkdir(parents=True, exist_ok=True)
    (root / ".metadata_never_index").touch(exist_ok=True)


def discard_xcode_app(app: Path) -> None:
    """Unregister and remove the transient app after it has been staged."""
    if not app.exists() and not app.is_symlink():
        return
    if _LSREGISTER.is_file():
        subprocess.run(
            [str(_LSREGISTER), "-u", str(app)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    if app.is_symlink():
        app.unlink()
    else:
        shutil.rmtree(app)


def xcodebuild_environment() -> dict[str, str]:
    """Select a complete Xcode installation for release builds.

    ``xcode-select`` is often pointed at CommandLineTools even when Xcode is
    installed. Release builds need the full SDK and project builder, so the
    normal Xcode locations are discovered automatically instead of requiring
    a manual ``DEVELOPER_DIR`` export for every invocation.
    """
    environment = os.environ.copy()
    configured = environment.get("DEVELOPER_DIR", "").strip()
    candidates: list[str] = []
    if configured:
        candidates.append(configured)
    try:
        selected = subprocess.check_output(
            ["xcode-select", "-p"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        selected = ""
    if selected:
        candidates.append(selected)
    candidates.extend([
        "/Applications/Xcode.app/Contents/Developer",
        "/Applications/Xcode-beta.app/Contents/Developer",
    ])

    seen: set[str] = set()
    for candidate in candidates:
        resolved = str(Path(candidate).expanduser())
        if resolved in seen:
            continue
        seen.add(resolved)
        xcodebuild = Path(resolved) / "usr/bin/xcodebuild"
        if not xcodebuild.is_file():
            continue
        selected_environment = {
            **environment,
            "DEVELOPER_DIR": resolved,
        }
        try:
            subprocess.run(
                [str(xcodebuild), "-version"],
                env=selected_environment,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.CalledProcessError):
            continue
        return selected_environment

    raise ValueError(
        "a complete Xcode installation is required for release builds; "
        "install Xcode or set DEVELOPER_DIR to its Contents/Developer path"
    )


def build_release(
    *,
    version: str,
    source_revision: str,
    output: Path,
    signing_identity: str | None = None,
) -> Path:
    if not _REVISION.fullmatch(source_revision):
        raise ValueError("source revision must be a full lowercase Git SHA")
    _validate_source_checkout(REPO, source_revision)
    if output.exists():
        raise ValueError(f"release output already exists: {output}")
    source_app = (
        REPO
        / "apple/build/Build/Products/Release/FTClient.app"
    )
    if not (source_app / "Contents" / "Info.plist").is_file():
        raise ValueError(f"macOS application is incomplete: {source_app}")
    with (source_app / "Contents" / "Info.plist").open("rb") as stream:
        app_identity = plistlib.load(stream)
    validate_embedded_sparkle_key(source_app)
    if app_identity.get("CFBundleShortVersionString") != version:
        raise ValueError("release version does not match the macOS app")
    build = str(app_identity.get("CFBundleVersion") or "")
    if not build.isdigit() or int(build) < 1:
        raise ValueError("macOS app build must be a positive integer")
    output.mkdir(parents=True)
    app = output / ".staging" / "FTClient.app"
    shutil.copytree(source_app, app, symlinks=True)
    embed_client_runtime(
        REPO,
        app,
        version=f"bundle-b{build}-r{source_revision}",
        source_revision=source_revision,
    )
    _sign_embedded_app(app, signing_identity)
    dmg = build_installer_dmg(app, output / "FactorTester-Client.dmg")
    shutil.rmtree(output / ".staging")
    return dmg


def validate_embedded_sparkle_key(
    app: Path,
    *,
    expected: str | None = None,
) -> None:
    """Reject an appcast-incompatible bundle before it can be published.

    Sparkle reads ``SUPublicEDKey`` from the installed app.  A missing or
    empty value makes the client fail its update check even when the server
    appcast is valid, so this is a release invariant rather than a runtime
    warning.
    """
    info_path = app / "Contents" / "Info.plist"
    if not info_path.is_file():
        raise ValueError(f"macOS application is missing Info.plist: {app}")
    with info_path.open("rb") as stream:
        info = plistlib.load(stream)
    actual = str(info.get("SUPublicEDKey") or "").strip()
    if not actual:
        raise ValueError("release app embeds an empty SUPublicEDKey")
    if expected is not None and actual != expected.strip():
        raise ValueError("release app embeds a different SUPublicEDKey")


def _sign_embedded_app(app: Path, signing_identity: str | None) -> None:
    """Sign nested code from the inside out with one stable identity."""
    if not signing_identity or signing_identity.strip() == "-":
        raise ValueError(
            "a stable signing identity is required; ad-hoc signatures "
            "invalidate persisted macOS privacy grants after updates"
        )
    timestamp = (
        "--timestamp"
        if signing_identity.startswith("Developer ID Application")
        else "--timestamp=none"
    )
    signables: list[Path] = []
    for path in app.rglob("*"):
        if path.is_symlink():
            continue
        if path.is_dir() and path.suffix in {".app", ".xpc", ".framework"}:
            signables.append(path)
        elif path.is_file() and (
            path.suffix in {".dylib", ".so"}
            or _is_mach_o(path)
        ):
            signables.append(path)
    signables.sort(key=lambda path: len(path.parts), reverse=True)
    runtime_bin = app / "Contents/Resources/FactorTester/bin"
    entitlements = str(
        REPO / "apple/Resources/macOS/FactorTester-Client.entitlements"
    )
    for path in signables:
        command = [
            "codesign", "--force", "--sign", signing_identity,
            "--options", "runtime", timestamp,
        ]
        if path.is_relative_to(runtime_bin):
            command.extend(["--entitlements", entitlements])
        command.append(str(path))
        subprocess.run(
            command,
            check=True,
            capture_output=True,
        )
    runtime_resources = app / "Contents/Resources/FactorTester"
    if (runtime_resources / "bundle-receipt.json").is_file():
        refresh_runtime_receipt(runtime_resources)
    subprocess.run(
        [
            "codesign", "--force", "--sign", signing_identity,
            "--options", "runtime", timestamp,
            "--entitlements", entitlements,
            str(app),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["codesign", "--verify", "--strict", "--all-architectures", str(app)],
        check=True,
        capture_output=True,
    )
    entitlements = subprocess.run(
        ["codesign", "-d", "--entitlements", ":-", str(app)],
        check=True,
        capture_output=True,
    )
    entitlement_payload = entitlements.stdout + entitlements.stderr
    if isinstance(entitlement_payload, str):
        entitlement_payload = entitlement_payload.encode()
    if b"com.apple.security.cs.disable-library-validation" not in entitlement_payload:
        raise ValueError(
            "release signature is missing Sparkle library-validation entitlement"
        )
    requirement = subprocess.run(
        ["codesign", "-d", "-r-", str(app)],
        check=True,
        capture_output=True,
        text=True,
    )
    requirement_text = (requirement.stdout or "") + (requirement.stderr or "")
    if "designated => cdhash" in requirement_text:
        raise ValueError(
            "release signature does not have a stable designated requirement"
        )


def _is_mach_o(path: Path) -> bool:
    result = subprocess.run(
        ["/usr/bin/file", "--brief", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return "Mach-O" in result.stdout


def _validate_source_checkout(repo: Path, source_revision: str) -> None:
    observed = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()
    if observed != source_revision:
        raise ValueError(
            "source revision does not match the release checkout: "
            f"expected {source_revision}, observed {observed}; "
            "use `git rev-parse HEAD` from this checkout"
        )
    status = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=repo,
        text=True,
    )
    if status.strip():
        raise ValueError("release checkout contains unpublished client changes")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--signing-identity",
        required=True,
        help="persistent Keychain identity or Developer ID Application identity",
    )
    args = parser.parse_args()
    try:
        print(build_release(**vars(args)))
    except Exception:
        if args.output.exists():
            shutil.rmtree(args.output)
        raise


if __name__ == "__main__":
    main()
