#!/usr/bin/env python3
"""Create or update isolated conda workers for supported backtest engines."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_DIR = REPO_ROOT / "environments"
FRAMEWORKS = ("backtrader", "qlib", "zipline")


def environment_names() -> set[str]:
    result = subprocess.run(
        ["conda", "env", "list", "--json"],
        check=True,
        capture_output=True,
        text=True,
    )
    return {Path(prefix).name for prefix in json.loads(result.stdout)["envs"]}


def run(command: list[str]) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=REPO_ROOT, check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "frameworks",
        nargs="*",
        default=None,
    )
    parser.add_argument("--prefix", default="GTHT-")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    unknown = set(args.frameworks or ()) - set(FRAMEWORKS)
    if unknown:
        raise ValueError(f"unknown backtest frameworks: {sorted(unknown)}")
    existing = environment_names()
    for framework in args.frameworks or FRAMEWORKS:
        name = f"{args.prefix}{framework}"
        action = "update" if name in existing else "create"
        command = [
            "conda",
            "env",
            action,
            "-n",
            name,
            "-f",
            str(ENV_DIR / f"{framework}.yml"),
        ]
        if action == "create":
            command.append("-y")
        run(command)
        module = "zipline" if framework == "zipline" else framework
        run([
            "conda",
            "run",
            "-n",
            name,
            "python",
            "-c",
            f"import {module}; print({module}.__version__)",
        ])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
