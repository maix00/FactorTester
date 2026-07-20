"""Assemble one signed, offline-installable FactorTester client release."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil

from script.release.assets import (
    embed_client_runtime,
    build_installer_dmg,
)


REPO = Path(__file__).resolve().parents[2]


def build_release(
    *,
    version: str,
    source_revision: str,
    output: Path,
) -> Path:
    if output.exists():
        raise ValueError(f"release output already exists: {output}")
    output.mkdir(parents=True)
    source_app = (
        REPO
        / "apple/build/Build/Products/Release/FactorTester-Client.app"
    )
    if not (source_app / "Contents" / "Info.plist").is_file():
        raise ValueError(f"macOS application is incomplete: {source_app}")
    app = output / ".staging" / "FactorTester-Client.app"
    shutil.copytree(source_app, app)
    embed_client_runtime(
        REPO,
        app,
        version=version,
        source_revision=source_revision,
    )
    dmg = build_installer_dmg(app, output / "FactorTester-Client.dmg")
    shutil.rmtree(output / ".staging")
    return dmg


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
