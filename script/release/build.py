"""Assemble one signed, offline-installable FactorTester client release."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys

from script.release.assets import build_app_archive, build_python_assets
from script.release.manifest import create_manifest, write_manifest
from tools.cli.release.contracts import validate_release_manifest


REPO = Path(__file__).resolve().parents[2]


def build_release(
    *,
    version: str,
    output: Path,
    private_key: Path,
    base_url: str,
) -> Path:
    if output.exists():
        raise ValueError(f"release output already exists: {output}")
    output.mkdir(parents=True)
    assets = build_python_assets(REPO, output)
    app = REPO / "apple/build/Build/Products/Release/GTHTClient.app"
    assets.append(build_app_archive(app, output / "GTHTClient.zip"))
    adapter = output / "vibe-trading-adapter.zip"
    subprocess.run(
        [
            sys.executable,
            str(REPO / "client-adapters/vibe-trading/build_archive.py"),
            str(adapter),
        ],
        check=True,
    )
    assets.append(adapter)
    public_key = REPO / "tools/cli/release/trusted-release-public.pem"
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    manifest = create_manifest(
        version=version,
        revision=revision,
        base_url=base_url,
        assets=assets,
        private_key=private_key,
        public_key=public_key,
    )
    validate_release_manifest(manifest, public_key=public_key)
    return write_manifest(output / "release-manifest.json", manifest)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--private-key", required=True, type=Path)
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    try:
        print(build_release(**vars(args)))
    except Exception:
        if args.output.exists():
            shutil.rmtree(args.output)
        raise


if __name__ == "__main__":
    main()
