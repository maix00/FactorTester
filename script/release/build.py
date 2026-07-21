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
)


REPO = Path(__file__).resolve().parents[2]
_REVISION = re.compile(r"^[0-9a-f]{40}$")


def build_release(
    *,
    version: str,
    source_revision: str,
    output: Path,
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
    shutil.copytree(source_app, app)
    embed_client_runtime(
        REPO,
        app,
        version=f"bundle-b{build}-r{source_revision}",
        source_revision=source_revision,
    )
    dmg = build_installer_dmg(app, output / "FactorTester-Client.dmg")
    shutil.rmtree(output / ".staging")
    return dmg


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
    args = parser.parse_args()
    try:
        print(build_release(**vars(args)))
    except Exception:
        if args.output.exists():
            shutil.rmtree(args.output)
        raise


if __name__ == "__main__":
    main()
