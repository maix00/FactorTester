"""Create one compact signed stable/beta update-channel manifest."""

from __future__ import annotations

import argparse
from pathlib import Path

from tools.cli.release.update_manifest_authoring import (
    create_update_manifest,
    write_update_manifest,
)
from tools.cli.release.update_manifest_authoring import (
    verify_installer as verify_installer,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--build", required=True, type=int)
    parser.add_argument("--channel", choices=("stable", "beta"), required=True)
    parser.add_argument("--dmg", required=True, type=Path)
    parser.add_argument("--dmg-url", required=True)
    parser.add_argument("--minimum-client", required=True)
    parser.add_argument("--mandatory", action="store_true")
    parser.add_argument("--published-at", required=True)
    parser.add_argument("--private-key", required=True, type=Path)
    parser.add_argument("--public-key", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = vars(parser.parse_args())
    output = args.pop("output")
    write_update_manifest(output, create_update_manifest(**args))
    print(output)


if __name__ == "__main__":
    main()
