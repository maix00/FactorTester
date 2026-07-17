"""Server-managed paths and quota defaults for retained job results."""

from __future__ import annotations

import os
from pathlib import Path

import settings as Settings


DEFAULT_USER_QUOTA_BYTES = 5 * 1024 * 1024 * 1024


def artifact_root() -> Path:
    configured = os.environ.get("GTHT_JOB_ARTIFACT_ROOT")
    root = Path(configured).expanduser() if configured else Settings.CACHE_DIR / "research-job-results"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def default_user_quota_bytes() -> int:
    return max(
        0,
        int(os.environ.get("GTHT_JOB_USER_QUOTA_BYTES", str(DEFAULT_USER_QUOTA_BYTES))),
    )
