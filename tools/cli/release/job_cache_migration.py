"""Validate and migrate the local Job artifact cache.

The desktop client has one canonical cache at ``Documents/FactorTester/jobs``.
Older client workspaces can be supplied as source roots for a one-time,
hash-checked copy.  The operation is idempotent and never removes a source.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .job_cache_inventory import digest, inspect


def _copy_atomic(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".migration.tmp", dir=target.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as destination, source.open("rb") as stream:
            shutil.copyfileobj(stream, destination, length=1024 * 1024)
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary_name, target)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def migrate(report: dict[str, Any], *, apply: bool) -> dict[str, Any]:
    if not apply:
        return {**report, "applied": False, "copied": 0}
    canonical_root = Path(report["canonical_root"])
    copied = 0
    for item in report["items"]:
        if item["location"] != "source":
            continue
        source = Path(item["path"])
        target = canonical_root / item["job_id"] / item["file_name"]
        if target.is_file() and digest(target) == (
            item["content_hash"], int(item["size_bytes"])
        ):
            continue
        _copy_atomic(source, target)
        if digest(target) != (item["content_hash"], int(item["size_bytes"])):
            raise RuntimeError(f"cache migration verification failed: {target}")
        copied += 1
    return {**report, "applied": True, "copied": copied}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical-root", required=True, type=Path)
    parser.add_argument("--source-root", action="append", default=[], type=Path)
    parser.add_argument("--apply", action="store_true", help="copy verified bytes")
    return parser


def main() -> int:
    args = _parser().parse_args()
    report = inspect(
        args.canonical_root.expanduser(),
        [path.expanduser() for path in args.source_root],
    )
    result = migrate(report, apply=args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not result["counts"]["conflict"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
