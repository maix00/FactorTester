"""Assemble one signed, offline-installable FactorTester client release."""

from __future__ import annotations

import argparse
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
    for path in signables:
        subprocess.run(
            [
                "codesign", "--force", "--sign", signing_identity,
                "--options", "runtime", timestamp, str(path),
            ],
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
            "--entitlements",
            str(REPO / "apple/Resources/macOS/FactorTester-Client.entitlements"),
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
        raise ValueError("source revision does not match the release checkout")
    status = subprocess.check_output(
        [
            "git", "status", "--porcelain", "--untracked-files=all", "--",
            "apple", "tools/cli", "client-adapters", "script",
        ],
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
