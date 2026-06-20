"""Inspect or build registered derived market-data artifacts."""

from __future__ import annotations

import argparse
import json

from sources import load_all_sources
from tools.data.artifacts import ArtifactCoordinator


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("inspect", "ensure", "build"))
    parser.add_argument("artifact_key", nargs="?")
    args = parser.parse_args(argv)

    load_all_sources()
    coordinator = ArtifactCoordinator()
    if args.action == "inspect":
        result = coordinator.inspect_all()
    elif args.artifact_key:
        result = coordinator.ensure(args.artifact_key, force=args.action == "build")
    else:
        result = coordinator.ensure_all(force=args.action == "build")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
