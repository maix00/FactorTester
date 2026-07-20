"""Build a deterministic Vibe-Trading client adapter archive."""

from __future__ import annotations

import argparse
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parent
FILES = ("adapter.json", "bin/start", "bin/health", "bin/open", "bin/stop")


def build(output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for relative in FILES:
            source = ROOT / relative
            info = zipfile.ZipInfo(relative, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o100755 if relative.startswith("bin/") else 0o100644
            info.external_attr = mode << 16
            archive.writestr(info, source.read_bytes())
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(build(args.output))


if __name__ == "__main__":
    main()
