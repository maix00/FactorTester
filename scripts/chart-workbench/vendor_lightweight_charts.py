"""Stage the pinned Lightweight Charts release for the shared static shell.

The Git submodule is the reviewable source checkout. The npm release is the
prebuilt, integrity-pinned browser artifact for that same upstream tag; no
node_modules or network fetch is needed at Manager runtime.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "third_party" / "lightweight-charts"
TARGET = ROOT / "static" / "vendor" / "lightweight-charts"
MANIFEST = ROOT / "server" / "manager" / "web" / "module-manifest.json"
VERSION = "5.2.1"
SOURCE_COMMIT = "b2ce010e4ad59f6556c9ed60e2b2b30feccdd2d1"
NPM_INTEGRITY = "sha512-IVwoK1RLFiLPubaKIjNbtjWLnpPMqiABSrTay6whmNa8L1+19292VtHJ+BWyPUuLCwF0tcQlhEWd1CLB2a1nsQ=="
ASSETS = (
    "lightweight-charts.standalone.production.js",
    "LICENSE",
    "NOTICE",
    "UPSTREAM",
)


def _read_release(tarball: Path) -> bytes:
    algorithm, encoded_digest = NPM_INTEGRITY.split("-", 1)
    if algorithm != "sha512":
        raise RuntimeError("unsupported npm integrity algorithm")
    actual = hashlib.sha512(tarball.read_bytes()).digest()
    if actual != base64.b64decode(encoded_digest):
        raise RuntimeError("Lightweight Charts release integrity mismatch")
    with tarfile.open(tarball, "r:gz") as archive:
        package = json.load(archive.extractfile("package/package.json"))
        if package.get("version") != VERSION:
            raise RuntimeError("Lightweight Charts release version mismatch")
        script = archive.extractfile(
            "package/dist/lightweight-charts.standalone.production.js"
        )
        if script is None:
            raise RuntimeError("Lightweight Charts browser build is missing")
        return script.read()


def main() -> None:
    actual = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=SOURCE, text=True
    ).strip()
    if actual != SOURCE_COMMIT:
        raise RuntimeError(f"submodule is not the pinned v{VERSION} source: {actual}")
    source_version = json.loads((SOURCE / "package.json").read_text())["version"]
    if source_version != VERSION:
        raise RuntimeError("submodule source version mismatch")

    with tempfile.TemporaryDirectory(prefix="ft-lightweight-charts-") as folder:
        result = subprocess.run(
            ["npm", "pack", f"lightweight-charts@{VERSION}", "--json", "--pack-destination", folder],
            check=True, capture_output=True, text=True,
        )
        filename = json.loads(result.stdout)[0]["filename"]
        browser_script = _read_release(Path(folder) / filename)

    TARGET.mkdir(parents=True, exist_ok=True)
    (TARGET / ASSETS[0]).write_bytes(browser_script)
    for name in ("LICENSE", "NOTICE"):
        (TARGET / name).write_bytes((SOURCE / name).read_bytes())
    (TARGET / "UPSTREAM").write_text(
        "source=https://github.com/maix00/lightweight-charts\n"
        "upstream=https://github.com/tradingview/lightweight-charts\n"
        f"tag=v{VERSION}\ncommit={SOURCE_COMMIT}\n"
        f"npm_integrity={NPM_INTEGRITY}\n"
        f"browser_sha256={hashlib.sha256(browser_script).hexdigest()}\n"
    )

    manifest = json.loads(MANIFEST.read_text())
    declared = manifest.setdefault("vendor_assets", [])
    for name in ASSETS:
        asset = f"vendor/lightweight-charts/{name}"
        if asset not in declared:
            declared.append(asset)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n")


if __name__ == "__main__":
    main()
