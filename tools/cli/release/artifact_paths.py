"""Safe local paths for individually downloaded Job artifacts."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any


def artifact_destination(root: Path, metadata: dict[str, Any]) -> Path:
    """Map server metadata to one bounded output path without a ZIP archive."""

    file_name = _safe_name(metadata.get("file_name") or metadata.get("name"))
    parts = [file_name]
    if str(metadata.get("role") or "output") == "input":
        kind = re.sub(
            r"[^A-Za-z0-9_-]+", "-", str(metadata.get("artifact_kind") or "input"),
        ).strip("-") or "input"
        logical = _safe_parts(metadata.get("logical_path"))
        parts = ["inputs", kind, *(logical or [file_name])]
    base = root.expanduser().resolve()
    target = (base / Path(*parts)).resolve()
    if base not in target.parents:
        raise ValueError("Job artifact path escapes the output directory")
    return target


def _safe_name(value: object) -> str:
    name = Path(str(value or "artifact").replace("\\", "/")).name
    if name in {"", ".", ".."}:
        raise ValueError("Job artifact file name is invalid")
    return name


def _safe_parts(value: object) -> list[str]:
    raw = str(value or "").replace("\\", "/")
    path = PurePosixPath(raw)
    parts = [part for part in path.parts if part not in {"", "."}]
    if path.is_absolute() or ".." in parts:
        return []
    return parts


__all__ = ["artifact_destination"]
