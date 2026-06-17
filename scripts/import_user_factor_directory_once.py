#!/usr/bin/env python3
"""One-time migration from a user's local factor directory into SQLite."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.data.factor_workspace.storage import factor_source_root
from tools.data.sqlite.factor_source_store import upsert_factor_source


def import_user_factor_directory_once(username: str, source_root: str | None = None) -> dict[str, object]:
    root = os.path.abspath(os.path.expanduser(source_root)) if source_root else factor_source_root(username)
    custom_dir = os.path.join(root, 'custom_factors')
    imported = 0
    skipped = 0
    imported_ids: list[str] = []

    if not os.path.isdir(custom_dir):
        return {
            'source_root': root,
            'custom_factor_dir': custom_dir,
            'imported_count': 0,
            'skipped_count': 0,
            'imported_ids': [],
        }

    for filename in sorted(os.listdir(custom_dir)):
        if not filename.endswith('.py'):
            continue
        factor_id = filename[:-3]
        path = os.path.join(custom_dir, filename)
        if not os.path.isfile(path):
            skipped += 1
            continue
        with open(path, 'r', encoding='utf-8') as file:
            source_code = file.read()
        if not source_code.strip():
            skipped += 1
            continue
        upsert_factor_source('custom', username, factor_id, factor_id, source_code)
        imported += 1
        imported_ids.append(factor_id)

    return {
        'source_root': root,
        'custom_factor_dir': custom_dir,
        'imported_count': imported,
        'skipped_count': skipped,
        'imported_ids': imported_ids,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description='Import local user FactorFamily source files into SQLite once.')
    parser.add_argument('--username', required=True)
    parser.add_argument('--source-root', default=None)
    args = parser.parse_args()
    result = import_user_factor_directory_once(args.username, args.source_root)
    print(result)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
