#!/usr/bin/env python3
"""One-time migration from legacy user template JSON files into SQLite."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.data_dir import DATA_DIR
from tools.data.account_manage import save_user_templates


def _load_templates(path: str) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as file:
        data = json.load(file)
    if isinstance(data, dict) and isinstance(data.get("templates"), list):
        return [item for item in data["templates"] if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _kind_from_filename(filename: str) -> str:
    if filename.endswith("_templates.json"):
        return filename[: -len("_templates.json")]
    if filename.endswith(".json"):
        return filename[:-5]
    return filename


def _import_file(username: str, kind: str, path: str, *, ff_alias: str | None = None, scope_key: str | None = None) -> int:
    templates = _load_templates(path)
    if not templates:
        return 0
    save_user_templates(username, kind, templates, ff_alias=ff_alias, scope_key=scope_key)
    return len(templates)


def import_user_templates_once(source_root: str | None = None) -> dict[str, Any]:
    root = os.path.abspath(os.path.expanduser(source_root or os.path.join(DATA_DIR, "user_storage")))
    result = {
        "source_root": root,
        "users": 0,
        "collections": 0,
        "templates": 0,
        "skipped": 0,
    }
    if not os.path.isdir(root):
        return result

    for username in sorted(os.listdir(root)):
        if username.startswith(".") or username.startswith("_"):
            continue
        user_dir = os.path.join(root, username)
        if not os.path.isdir(user_dir):
            continue
        result["users"] += 1

        for name in sorted(os.listdir(user_dir)):
            path = os.path.join(user_dir, name)
            if os.path.isfile(path) and name.endswith("_templates.json"):
                try:
                    count = _import_file(username, _kind_from_filename(name), path)
                except Exception:
                    result["skipped"] += 1
                    continue
                if count:
                    result["collections"] += 1
                    result["templates"] += count
                continue

            if not os.path.isdir(path) or not name.endswith("_templates"):
                continue
            kind = name[: -len("_templates")]
            for child in sorted(os.listdir(path)):
                child_path = os.path.join(path, child)
                if os.path.isfile(child_path) and child.endswith(".json"):
                    key = child[:-5]
                    try:
                        if kind == "params":
                            count = _import_file(username, kind, child_path, ff_alias=key)
                        else:
                            count = _import_file(username, kind, child_path, scope_key=key)
                    except Exception:
                        result["skipped"] += 1
                        continue
                    if count:
                        result["collections"] += 1
                        result["templates"] += count
                    continue

                if not os.path.isdir(child_path):
                    continue
                scope_key = child
                for filename in sorted(os.listdir(child_path)):
                    file_path = os.path.join(child_path, filename)
                    if not os.path.isfile(file_path) or not filename.endswith(".json"):
                        continue
                    ff_alias = filename[:-5]
                    try:
                        count = _import_file(username, kind, file_path, ff_alias=ff_alias, scope_key=scope_key)
                    except Exception:
                        result["skipped"] += 1
                        continue
                    if count:
                        result["collections"] += 1
                        result["templates"] += count

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Import legacy user template JSON files into SQLite once.")
    parser.add_argument("--source-root", default=None, help="Legacy user_storage root. Defaults to DATA_DIR/user_storage.")
    args = parser.parse_args()
    print(import_user_templates_once(args.source_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
