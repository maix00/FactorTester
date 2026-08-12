"""Bounded, non-executable files retained with one research Run."""

from __future__ import annotations

import hashlib
import mimetypes
from pathlib import PurePosixPath
from typing import Any, Iterable


MAX_FILES = 200
MAX_INPUT_BYTES = 20 * 1024 * 1024
MAX_PATH_CHARS = 240
MAX_TITLE_CHARS = 80
SUPPORTED_SUFFIXES = {
    ".cfg", ".csv", ".ini", ".json", ".md", ".py", ".toml",
    ".txt", ".yaml", ".yml",
}
SUPPORTED_PURPOSES = {
    "strategy_dependency", "strategy_configuration", "run_configuration",
    "data_mapping", "documentation", "other",
}
CONTENT_TYPES = {
    ".cfg": "text/plain",
    ".csv": "text/csv",
    ".ini": "text/plain",
    ".json": "application/json",
    ".md": "text/markdown",
    ".py": "text/x-python",
    ".toml": "application/toml",
    ".txt": "text/plain",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
}


def _path(value: Any) -> PurePosixPath:
    raw = str(value or "").replace("\\", "/").strip()
    path = PurePosixPath(raw)
    if (
        not raw or len(raw) > MAX_PATH_CHARS or path.is_absolute()
        or ".." in path.parts or not path.name or raw.startswith("./")
    ):
        raise ValueError("run input dependency path must be a safe relative path")
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError("run input dependency must be a supported text file")
    return path


def validate_entries(
    raw: Any,
    *,
    analyses: Iterable[str],
) -> list[dict[str, Any]]:
    """Validate source text without granting it execution authority."""
    if raw in (None, []):
        return []
    if not isinstance(raw, list) or len(raw) > MAX_FILES:
        raise ValueError("run_input_dependencies must be a bounded array")
    allowed_analyses = tuple(dict.fromkeys(str(item) for item in analyses))
    allowed_set = set(allowed_analyses)
    if not allowed_set:
        raise ValueError("run input dependency requires at least one analysis")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    total = 0
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("run input dependency must be an object")
        path = _path(item.get("path"))
        normalized_path = path.as_posix()
        if normalized_path in seen:
            raise ValueError(f"duplicate run input dependency: {normalized_path}")
        content = item.get("content")
        if not isinstance(content, str) or not content:
            raise ValueError(f"run input dependency is empty: {normalized_path}")
        encoded = content.encode("utf-8")
        total += len(encoded)
        if total > MAX_INPUT_BYTES:
            raise ValueError("run input dependency bundle exceeds size limit")
        selected = item.get("analyses")
        if selected in (None, []):
            selected_analyses = list(allowed_analyses)
        elif isinstance(selected, list):
            selected_analyses = list(dict.fromkeys(str(value) for value in selected))
        else:
            raise ValueError("run input dependency analyses must be an array")
        if not selected_analyses or not set(selected_analyses) <= allowed_set:
            raise ValueError("run input dependency analysis is not in this Run")
        purpose = str(item.get("purpose") or "other").strip()
        if purpose not in SUPPORTED_PURPOSES:
            raise ValueError("run input dependency purpose is invalid")
        title = str(item.get("title_zh") or path.name).strip()
        if not title or len(title) > MAX_TITLE_CHARS:
            raise ValueError("run input dependency title_zh is invalid")
        suffix = path.suffix.lower()
        content_type = CONTENT_TYPES.get(
            suffix,
            mimetypes.guess_type(path.name)[0] or "text/plain",
        )
        seen.add(normalized_path)
        result.append({
            "path": normalized_path,
            "file_name": path.name,
            "content": content,
            "content_type": content_type,
            "title_zh": title,
            "purpose": purpose,
            "analyses": selected_analyses,
            "source_sha256": hashlib.sha256(encoded).hexdigest(),
            "source_bytes": len(encoded),
        })
    return result


def source_free_manifest(entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in item.items() if key != "content"}
        for item in entries
    ]


def dependency_input_bytes(
    entries: Iterable[dict[str, Any]],
    *,
    analysis: str | None = None,
) -> int:
    return sum(
        int(item.get("source_bytes") or 0)
        for item in entries
        if analysis is None or analysis in (item.get("analyses") or ())
    )
