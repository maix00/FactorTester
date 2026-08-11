"""One-time migration of retained Job artifacts into the shared root.

Artifact paths stored in the Job database are root-relative (``job_id/name``).
The migration therefore moves bytes, not database identities.  Every source
byte is checked against the recorded size and SHA-256 before it is accepted.
The command is deliberately idempotent and never removes an old source.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterable

from tools.data.sqlite.db import connect_sqlite


def _safe_relative(value: str) -> Path:
    relative = Path(str(value))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe artifact path: {value!r}")
    return relative


def _digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _valid_candidate(path: Path, expected_hash: str, expected_size: int) -> bool:
    if not path.is_file():
        return False
    actual_hash, actual_size = _digest(path)
    return actual_hash == expected_hash and actual_size == expected_size


def _rows(db_path: Path) -> list[Any]:
    with connect_sqlite(db_path) as connection:
        return list(connection.execute(
            """
            SELECT job_id, name, relative_path, content_hash, size_bytes, state
            FROM research_job_artifacts
            WHERE state <> 'deleted'
            ORDER BY job_id, name
            """
        ))


def inspect(
    db_path: Path,
    canonical_root: Path,
    source_roots: Iterable[Path],
) -> dict[str, Any]:
    roots = [canonical_root, *source_roots]
    rows = _rows(db_path)
    items: list[dict[str, Any]] = []
    counts = {"canonical": 0, "source": 0, "missing": 0, "conflict": 0}
    for row in rows:
        relative = _safe_relative(str(row["relative_path"]))
        expected_hash = str(row["content_hash"])
        expected_size = int(row["size_bytes"])
        location = "missing"
        path_value = ""
        mismatches: list[str] = []
        for index, root in enumerate(roots):
            candidate = (root / relative).resolve()
            if root.resolve() not in candidate.parents:
                mismatches.append(str(candidate))
                continue
            if not candidate.exists():
                continue
            if _valid_candidate(candidate, expected_hash, expected_size):
                location = "canonical" if index == 0 else "source"
                path_value = str(candidate)
                break
            mismatches.append(str(candidate))
        if location == "missing" and mismatches:
            location = "conflict"
        counts[location] += 1
        items.append({
            "job_id": str(row["job_id"]),
            "name": str(row["name"]),
            "relative_path": str(relative),
            "size_bytes": expected_size,
            "content_hash": expected_hash,
            "state": str(row["state"]),
            "location": location,
            "path": path_value,
            "mismatches": mismatches,
        })
    return {
        "database": str(db_path),
        "canonical_root": str(canonical_root),
        "source_roots": [str(root) for root in source_roots],
        "artifact_count": len(rows),
        "counts": counts,
        "items": items,
    }


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
        if item["location"] == "canonical":
            continue
        if item["location"] != "source":
            continue
        source = Path(item["path"])
        target = canonical_root / _safe_relative(item["relative_path"])
        if target.is_file() and _valid_candidate(
            target, item["content_hash"], int(item["size_bytes"])
        ):
            continue
        _copy_atomic(source, target)
        if not _valid_candidate(target, item["content_hash"], int(item["size_bytes"])):
            raise RuntimeError(f"migration verification failed: {target}")
        copied += 1
    return {**report, "applied": True, "copied": copied}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--canonical-root", required=True, type=Path)
    parser.add_argument("--source-root", action="append", default=[], type=Path)
    parser.add_argument("--apply", action="store_true", help="copy verified bytes")
    return parser


def main() -> int:
    args = _parser().parse_args()
    report = inspect(
        args.db.expanduser().resolve(),
        args.canonical_root.expanduser().resolve(),
        [path.expanduser().resolve() for path in args.source_root],
    )
    result = migrate(report, apply=args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not result["counts"]["conflict"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
