"""Package reviewed Keycloak policies without downloading a JDK or dependencies."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


def build(destination: Path) -> None:
    source = Path(__file__).resolve().parents[2] / "deploy/docker/keycloak/policies/research-superiors.js"
    descriptor = {"policies": [{"name": "TradeResearch current superiors",
                               "fileName": "research-superiors.js",
                               "description": "Live administrator-owned parent relationships"}]}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
        for name, payload in (("META-INF/keycloak-scripts.json", json.dumps(descriptor).encode()),
                              ("research-superiors.js", source.read_bytes())):
            info = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, payload)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    build(parser.parse_args().output)
