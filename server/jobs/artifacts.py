"""Server-managed paths and quota defaults for retained job results."""

from __future__ import annotations

import os
import hashlib
import time
from pathlib import Path

import orjson

import settings as Settings


DEFAULT_USER_QUOTA_BYTES = 5 * 1024 * 1024 * 1024


def artifact_root() -> Path:
    configured = os.environ.get("GTHT_JOB_ARTIFACT_ROOT")
    root = Path(configured).expanduser() if configured else Settings.CACHE_DIR / "research-job-results"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def resolve_artifact_path(
    relative_path: str,
    *,
    expected_hash: str | None = None,
) -> Path:
    """Resolve a retained artifact from the single shared result root."""
    relative = Path(str(relative_path))
    if relative.is_absolute():
        raise FileNotFoundError("retained result file is unavailable")
    root = artifact_root()
    path = (root / relative).resolve()
    if root not in path.parents or not path.is_file():
        raise FileNotFoundError("retained result file is unavailable")
    if expected_hash:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != str(expected_hash):
            raise RuntimeError("retained result integrity check failed")
    return path


def default_user_quota_bytes() -> int:
    return max(
        0,
        int(os.environ.get("GTHT_JOB_USER_QUOTA_BYTES", str(DEFAULT_USER_QUOTA_BYTES))),
    )


def cleanup_staging_files(
    root: Path | str | None = None, *, max_age_seconds: float = 3600,
) -> int:
    """Remove abandoned atomic-write staging files without touching retained results."""
    base = Path(root).expanduser().resolve() if root is not None else artifact_root()
    if not base.exists():
        return 0
    cutoff = time.time() - max(0.0, float(max_age_seconds))
    removed = 0
    for path in base.rglob(".*.tmp"):
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except FileNotFoundError:
            continue
    return removed


def load_json_artifact(relative_path: str, expected_hash: str) -> object:
    path = resolve_artifact_path(relative_path, expected_hash=expected_hash)
    raw = path.read_bytes()
    return orjson.loads(raw)
