#!/usr/bin/env python3
"""Test alpha's adapter against the same Nautilus sources as the runtime.

No dependency/feature list is maintained here: source patches come from the
composition manifest, while dev-dependencies belong to the adapter workspace.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
COMPOSITION = ROOT / "native/traderesearch_nautilus_runtime/Cargo.toml"
ADAPTER = ROOT / "vendor/py-alpha-lib/adapters/nautilus/Cargo.toml"


def source_patch_args():
    manifest = tomllib.loads(COMPOSITION.read_text())
    result = []
    for name, patch in manifest["patch"]["crates-io"].items():
        path = (COMPOSITION.parent / patch["path"]).resolve()
        result.extend(["--config", f"patch.crates-io.{name}.path={json.dumps(str(path))}"])
    return result


def main():
    arguments = sys.argv[1:] or ["--lib", "--test", "catalog_runtime", "--", "--test-threads=1"]
    environment = dict(os.environ)
    environment.setdefault("CARGO_TARGET_DIR", str(ROOT / "vendor/nautilus_trader/target"))
    environment.setdefault("CARGO_PROFILE_DEV_OPT_LEVEL", "1")
    environment.setdefault("CARGO_BUILD_JOBS", "4")
    command = ["cargo", *source_patch_args(), "test", "--locked", "--manifest-path", str(ADAPTER),
               "--features", "nautilus-backtest", *arguments]
    return subprocess.call(command, cwd=ROOT / "vendor/nautilus_trader", env=environment)


if __name__ == "__main__":
    raise SystemExit(main())
