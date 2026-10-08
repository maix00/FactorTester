"""Stable local storage identity for a report and its authoring branches."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .package_layout import safe_package_component


IDENTITY_FILE = "report-workspace.json"
_LEGACY_IDENTITY_FILE = "work-package.json"


def report_workspace_id_for(report_id: str) -> str:
    report_id = _report_id(report_id)
    return "report-" + hashlib.sha256(report_id.encode("utf-8")).hexdigest()[:24]


def ensure_report_workspace_identity(
    report_root: Path,
    *,
    report_workspace_id: str,
    report_id: str,
    workspace_id: str = "",
    title: str = "",
) -> dict[str, Any]:
    """Create or verify the local identity manifest for one report workspace.

    Older report trees used a Work Package manifest as their storage carrier. Its
    report ID and authoring bytes are adopted into the report-native manifest; no
    Graph identity or Profile research projection is consulted.
    """
    from .authoring.tree_store import atomic_write

    root = Path(report_root).expanduser().resolve()
    workspace_key = safe_package_component(
        report_workspace_id, field="report_workspace_id",
    )
    logical_report_id = _report_id(report_id)
    path = root / IDENTITY_FILE
    existing_path = path if path.is_file() else root / _LEGACY_IDENTITY_FILE
    value: dict[str, Any] | None = None
    if existing_path.is_file():
        value = _load_existing_identity(existing_path)
    if value is not None:
        if value["report_workspace_id"] != workspace_key:
            raise ValueError("report workspace identity conflicts with its directory")
        if value["report_id"] != logical_report_id:
            raise ValueError("report workspace is already bound to another report")
        value = {
            **value,
            "workspace_id": str(workspace_id or value.get("workspace_id") or ""),
            "title": str(title or value.get("title") or ""),
        }
    else:
        value = {
            "schema_version": 1,
            "report_workspace_id": workspace_key,
            "report_id": logical_report_id,
            "workspace_id": str(workspace_id or ""),
            "title": str(title or ""),
        }
    value = _validate(value)
    if not path.is_file() or json.loads(path.read_text(encoding="utf-8")) != value:
        atomic_write(
            path,
            (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode(),
        )
    legacy_path = root / _LEGACY_IDENTITY_FILE
    if legacy_path.is_file():
        legacy_path.unlink()
    return value


def load_report_workspace_identity(report_root: Path) -> dict[str, Any]:
    root = Path(report_root).expanduser().resolve()
    path = root / IDENTITY_FILE
    if path.is_file():
        return _validate(json.loads(path.read_text(encoding="utf-8")))
    legacy = root / _LEGACY_IDENTITY_FILE
    if legacy.is_file():
        return _load_existing_identity(legacy)
    raise ValueError("report workspace identity is missing")


def _load_existing_identity(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("report workspace identity is invalid")
    if path.name == _LEGACY_IDENTITY_FILE:
        if set(value) != {"schema_version", "work_package_id", "report_id"}:
            raise ValueError("legacy report workspace identity is invalid")
        if value.get("schema_version") != 1:
            raise ValueError("legacy report workspace identity schema is unsupported")
        value = {
            "schema_version": 1,
            "report_workspace_id": value.get("work_package_id"),
            "report_id": value.get("report_id"),
            "workspace_id": "",
            "title": "",
        }
    return _validate(value)


def _validate(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "report_workspace_id", "report_id",
        "workspace_id", "title",
    } or value.get("schema_version") != 1:
        raise ValueError("report workspace identity is invalid")
    report_workspace_id = safe_package_component(
        value.get("report_workspace_id"), field="report_workspace_id",
    )
    report_id = _report_id(value.get("report_id"))
    workspace_id = str(value.get("workspace_id") or "")
    title = str(value.get("title") or "")
    if len(workspace_id.encode()) > 256 or len(title.encode()) > 512:
        raise ValueError("report workspace metadata is too long")
    return {
        "schema_version": 1,
        "report_workspace_id": report_workspace_id,
        "report_id": report_id,
        "workspace_id": workspace_id,
        "title": title,
    }


def _report_id(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 160:
        raise ValueError("report_id is invalid")
    text = value.strip()
    if any(char in text for char in "/\\\x00") or text.endswith(":"):
        raise ValueError("report_id is invalid")
    return text
