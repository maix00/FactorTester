#!/usr/bin/env python3
"""Explicitly collapse legacy per-Branch Report IDs inside one Work Package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.cli.release.research_reporting.work_package_identity import (
    migrate_work_package_report_identity,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("package_root", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(
        migrate_work_package_report_identity(
            args.package_root, apply=args.apply,
        ),
        ensure_ascii=False,
    ))


if __name__ == "__main__":
    main()
