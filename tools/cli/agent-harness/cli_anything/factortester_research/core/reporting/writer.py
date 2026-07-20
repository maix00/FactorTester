"""Atomic incremental writes for derived local research reports."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
from typing import Any, Protocol

from .markdown import MarkdownReportTarget
from .schema import canonical_report_snapshot


class ReportTarget(Protocol):
    """Render one canonical snapshot without external I/O."""

    media_type: str
    extension: str

    def render(self, snapshot: dict[str, Any]) -> bytes:
        """Return deterministic report bytes."""
        ...


def render_branch_report(
    snapshot: dict[str, Any],
    *,
    workspace_root: Path,
    target: ReportTarget | None = None,
) -> dict[str, Any]:
    """Atomically write one changed branch projection, or reuse it."""
    canonical = canonical_report_snapshot(snapshot)
    renderer = target or MarkdownReportTarget()
    payload = renderer.render(canonical)
    path = (
        Path(workspace_root)
        / "research"
        / "branches"
        / canonical["branch_id"]
        / f"REPORT{renderer.extension}"
    )
    content_hash = hashlib.sha256(payload).hexdigest()
    if path.exists() and path.read_bytes() == payload:
        return _result(path, False, content_hash, canonical["source_hash"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=path.parent,
        prefix=".report-",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return _result(path, True, content_hash, canonical["source_hash"])


def _result(
    path: Path,
    changed: bool,
    content_hash: str,
    source_hash: str,
) -> dict[str, Any]:
    return {
        "path": path,
        "changed": changed,
        "content_hash": content_hash,
        "source_hash": source_hash,
    }
