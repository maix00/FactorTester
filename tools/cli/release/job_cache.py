"""Persistent local cache for artifacts downloaded from remote Jobs."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Iterator
from tools.cli.local_paths import documents_root


_JOB_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_ROOT_ENV = "FACTORTESTER_JOB_CACHE_ROOT"
_MANIFEST = ".artifacts.json"


def default_job_cache_root() -> Path:
    configured = os.environ.get("TRADERESEARCH_JOB_CACHE_ROOT") or os.environ.get(_ROOT_ENV)
    root = (
        Path(configured).expanduser()
        if configured
        else documents_root() / "jobs"
    )
    return root.resolve()


@contextmanager
def job_cache_write_lock(job_id: str) -> Iterator[None]:
    """Serialize artifact publication for one Job across client processes."""
    from tools.cli.release.research_reporting.generation import _lock, _unlock

    directory = _job_directory(job_id)
    lock_path = directory / ".artifacts.lock"
    if directory.is_symlink() or lock_path.is_symlink():
        raise ValueError("Job cache lock cannot be a symlink")
    with lock_path.open("a+b") as handle:
        _lock(handle)
        try:
            yield
        finally:
            _unlock(handle)


def cache_job_artifact(
    *, job_id: str, name: str, filename: str, content_type: str,
    raw: bytes, server_url: str,
) -> dict[str, Any]:
    """Atomically persist one remote artifact under ``jobs/<job_id>``."""
    with job_cache_write_lock(job_id):
        return _cache_job_artifact_locked(
            job_id=job_id, name=name, filename=filename, content_type=content_type,
            raw=raw, server_url=server_url,
        )


def _cache_job_artifact_locked(
    *, job_id: str, name: str, filename: str, content_type: str,
    raw: bytes, server_url: str,
) -> dict[str, Any]:
    """Write while the caller holds this Job's cache lock."""
    directory = _job_directory(job_id)
    safe_name = _filename(filename)
    digest = hashlib.sha256(raw).hexdigest()
    target = directory / safe_name
    if not target.is_file() or _digest_path(target) != digest:
        staging = target.with_name(f".{safe_name}.part")
        staging.write_bytes(raw)
        staging.replace(target)
    manifest = _read_manifest(directory, job_id)
    manifest["server_url"] = str(server_url).rstrip("/")
    manifest["artifacts"][str(name)] = {
        "file_name": safe_name,
        "content_hash": digest,
        "content_type": str(content_type),
        "size_bytes": len(raw),
        "cached_at": time.time(),
    }
    _write_manifest(directory, manifest)
    return {"path": target, **manifest["artifacts"][str(name)]}


def cached_job_artifact(
    *, job_id: str, name: str, expected_hash: str = "",
) -> dict[str, Any] | None:
    """Return verified cached bytes only when their server hash still matches."""
    directory = _job_directory(job_id, create=False)
    manifest = _read_manifest(directory, job_id)
    item = manifest["artifacts"].get(str(name))
    if not isinstance(item, dict):
        return None
    digest = str(item.get("content_hash") or "")
    if not _HASH.fullmatch(digest) or (
        expected_hash and digest != expected_hash
    ):
        return None
    filename = _filename(str(item.get("file_name") or ""))
    path = directory / filename
    if not path.is_file() or _digest_path(path) != digest:
        return None
    return {"path": path, "raw": path.read_bytes(), **item}


def job_cache_directory(job_id: str) -> Path:
    """Expose the established cache location for CLI/UI integrations."""
    return _job_directory(job_id)


def _job_directory(job_id: str, *, create: bool = True) -> Path:
    if str(job_id) in {".", ".."} or not _JOB_ID.fullmatch(str(job_id)):
        raise ValueError("job_id is invalid for the local artifact cache")
    directory = default_job_cache_root() / str(job_id)
    if create:
        directory.mkdir(parents=True, exist_ok=True)
    return directory


def _read_manifest(directory: Path, job_id: str) -> dict[str, Any]:
    path = directory / _MANIFEST
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"schema_version": 1, "job_id": job_id, "artifacts": {}}
    if (
        not isinstance(value, dict) or value.get("schema_version") != 1
        or value.get("job_id") != job_id
        or not isinstance(value.get("artifacts"), dict)
    ):
        return {"schema_version": 1, "job_id": job_id, "artifacts": {}}
    return value


def _write_manifest(directory: Path, value: dict[str, Any]) -> None:
    target = directory / _MANIFEST
    staging = target.with_name(f".{target.name}.part")
    staging.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    staging.replace(target)


def _filename(value: str) -> str:
    name = Path(value).name
    if not name or name in {".", ".."} or len(name) > 255:
        raise ValueError("artifact filename is invalid")
    return name


def _digest_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
