"""Inventory and integrity checks for local Job cache manifests."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable


_HASH = re.compile(r"^[0-9a-f]{64}$")
_JOB_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def digest(path: Path) -> tuple[str, int]:
    checksum = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
            size += len(chunk)
    return checksum.hexdigest(), size


def safe_name(value: str) -> str:
    name = Path(str(value)).name
    if not name or name in {".", ".."} or name != str(value):
        raise ValueError(f"unsafe cache filename: {value!r}")
    return name


def _manifest(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or not isinstance(value.get("job_id"), str)
        or not _JOB_ID.fullmatch(value["job_id"])
        or not isinstance(value.get("artifacts"), dict)
    ):
        return None
    return value


def _files(root: Path) -> Iterable[tuple[Path, dict[str, Any]]]:
    if not root.is_dir():
        return
    for directory in sorted(root.iterdir()):
        if not directory.is_dir() or not _JOB_ID.fullmatch(directory.name):
            continue
        value = _manifest(directory / ".artifacts.json")
        if value is not None and value["job_id"] == directory.name:
            yield directory, value


def inspect(canonical_root: Path, source_roots: Iterable[Path]) -> dict[str, Any]:
    canonical_root = canonical_root.resolve()
    roots = [canonical_root, *(path.resolve() for path in source_roots)]
    entries: dict[tuple[str, str], list[tuple[int, Path, Any]]] = {}
    for root_index, root in enumerate(roots):
        for directory, value in _files(root):
            for name, metadata in value["artifacts"].items():
                entries.setdefault((value["job_id"], str(name)), []).append(
                    (root_index, directory, metadata)
                )

    items: list[dict[str, Any]] = []
    counts = {"canonical": 0, "source": 0, "missing": 0, "conflict": 0}
    for (job_id, name), candidates in sorted(entries.items()):
        fingerprints: set[tuple[str, str, int]] = set()
        manifests: list[str] = []
        filename = digest_value = ""
        size = -1
        for _, directory, metadata in candidates:
            manifests.append(str(directory / ".artifacts.json"))
            try:
                current = (
                    safe_name(str(metadata["file_name"])),
                    str(metadata["content_hash"]),
                    int(metadata["size_bytes"]),
                )
                if not _HASH.fullmatch(current[1]) or current[2] < 0:
                    raise ValueError("invalid artifact metadata")
            except (KeyError, TypeError, ValueError):
                current = ("", "", -1)
            fingerprints.add(current)
        location = "missing"
        path_value = ""
        mismatches: list[str] = []
        if len(fingerprints) == 1 and next(iter(fingerprints))[0]:
            filename, digest_value, size = next(iter(fingerprints))
            for index, root in enumerate(roots):
                candidate = root / job_id / filename
                if root not in candidate.resolve().parents:
                    mismatches.append(str(candidate))
                    continue
                if not candidate.is_file():
                    continue
                actual_digest, actual_size = digest(candidate)
                if actual_digest == digest_value and actual_size == size:
                    location = "canonical" if index == 0 else "source"
                    path_value = str(candidate)
                    break
                mismatches.append(str(candidate))
        else:
            location = "conflict"
        if location == "missing" and mismatches:
            location = "conflict"
        counts[location] += 1
        items.append({
            "job_id": job_id,
            "name": name,
            "file_name": filename,
            "size_bytes": size,
            "content_hash": digest_value,
            "location": location,
            "path": path_value,
            "mismatches": mismatches,
            "manifest": manifests,
        })
    return {
        "canonical_root": str(canonical_root),
        "source_roots": [str(path) for path in roots[1:]],
        "job_count": len({job_id for job_id, _ in entries}),
        "artifact_count": len(items),
        "counts": counts,
        "items": items,
    }
