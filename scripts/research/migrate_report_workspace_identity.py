#!/usr/bin/env python3
"""Unify legacy per-Branch Report IDs inside one Report Workspace."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.cli.release.research_reporting.report_identity_migration import (
    migrate_report_workspace_identity,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("package_root", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(
        migrate_report_workspace_identity(
            args.package_root, apply=args.apply,
        ),
        ensure_ascii=False,
    ))


if __name__ == "__main__":
    main()
