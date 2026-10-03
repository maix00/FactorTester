"""Build bounded, content-addressed attachments for shared reports.

The report tree is the primary publication.  This module only carries source
snapshots that a remote reader cannot resolve from the Manager/service
registries.  It deliberately does not walk a worktree or upload arbitrary
files: a binding must provide a relative path plus a matching Git blob.
"""

from __future__ import annotations

import base64
import hashlib
import mimetypes
import subprocess
from pathlib import Path
from typing import Any


MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024
MAX_ATTACHMENT_TOTAL = 20 * 1024 * 1024
_TEXT_SUFFIXES = {".py", ".pyi", ".json", ".yaml", ".yml", ".toml", ".md"}


def build_related_objects(
    snapshot: dict[str, Any],
    bindings: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return object inventory and bounded source attachments.

    Service-owned objects are represented by their stable references and a
    resolution hint.  Factor/factor-set source files are attached only when
    the path is inside the profile's factor worktree and the recorded Git blob
    matches exactly.
    """
    source_root = _factor_worktree(snapshot)
    objects: dict[tuple[str, str], dict[str, Any]] = {}
    attachments: dict[str, dict[str, Any]] = {}
    total = 0
    for value in bindings:
        target_ref = str(value.get("target_ref") or "")
        if not target_ref:
            continue
        kind = _object_kind(value.get("kind"), target_ref)
        data = value.get("data") if isinstance(value.get("data"), dict) else {}
        key = (kind, target_ref)
        item = objects.setdefault(key, {
            "object_kind": kind,
            "object_ref": target_ref,
            "title": str(value.get("label") or ""),
            "resolution": _resolution(kind, data),
            "snapshot": _public_metadata(data),
            "attachment_refs": [],
        })
        if not item["title"]:
            item["title"] = str(data.get("title_zh") or data.get("identity") or "")
        if kind not in {"factor", "factor_set"} or source_root is None:
            continue
        relative = _safe_relative(data.get("relative_path"))
        blob = str(data.get("blob_hash") or "")
        revision = str(data.get("revision") or "")
        if relative is None or not _git_blob(blob):
            continue
        path = source_root / relative
        if not path.is_file() or _git_blob_at(path) != blob:
            continue
        raw = path.read_bytes()
        if not raw or len(raw) > MAX_ATTACHMENT_BYTES or total + len(raw) > MAX_ATTACHMENT_TOTAL:
            continue
        content_hash = hashlib.sha256(raw).hexdigest()
        attachment_ref = f"attachment:sha256:{content_hash}"
        attachment = attachments.get(attachment_ref)
        if attachment is None:
            media_type = mimetypes.guess_type(path.name)[0] or (
                "text/plain" if path.suffix.lower() in _TEXT_SUFFIXES else
                "application/octet-stream"
            )
            attachment = {
                "attachment_ref": attachment_ref,
                "attachment_kind": "factor_source" if kind == "factor" else "factor_set_manifest",
                "filename": path.name,
                "relative_path": relative.as_posix(),
                "media_type": media_type,
                "content_hash": content_hash,
                "git_blob": blob,
                "revision": revision,
                "content_base64": base64.b64encode(raw).decode("ascii"),
            }
            attachments[attachment_ref] = attachment
            total += len(raw)
        if attachment_ref not in item["attachment_refs"]:
            item["attachment_refs"].append(attachment_ref)
    return sorted(objects.values(), key=lambda item: (item["object_kind"], item["object_ref"])), list(attachments.values())


def _object_kind(kind: Any, target_ref: str) -> str:
    value = str(kind or "").replace("-", "_")
    if target_ref.startswith("factor-set:") or value == "factor_set":
        return "factor_set"
    if value == "factor":
        return "factor"
    if value in {"run_spec", "trial_plan", "job", "run", "product", "product_group", "contract", "continuous_contract", "profile", "profile_revision", "evidence"}:
        return value
    return value or "object"


def _resolution(kind: str, data: dict[str, Any]) -> str:
    if kind in {"job", "run_spec", "trial_plan", "run"}:
        return "server_registry"
    if kind in {"factor", "factor_set"}:
        return "git_snapshot"
    if kind in {"product", "product_group", "contract", "continuous_contract"}:
        return "product_catalog_snapshot"
    if kind in {"profile", "profile_revision"}:
        return "profile_registry"
    if data.get("authority_scope"):
        return "server_registry"
    return "report_binding"


def _public_metadata(value: dict[str, Any]) -> dict[str, Any]:
    hidden = {"local_ref", "workspace_root", "receipt_path", "source_path", "content_base64"}
    return {
        str(key): item for key, item in value.items()
        if str(key) not in hidden
    }


def _factor_worktree(snapshot: dict[str, Any]) -> Path | None:
    root = snapshot.get("paths", {}).get("root")
    if not root:
        return None
    current = Path(root).resolve()
    for ancestor in (current, *current.parents):
        candidate = ancestor / "factor-worktree"
        if candidate.is_dir() and (candidate / ".git").exists():
            return candidate
    return None


def _safe_relative(value: Any) -> Path | None:
    text = str(value or "").strip()
    if not text or text.startswith("/"):
        return None
    path = Path(text)
    if any(part in {"", ".", ".."} for part in path.parts):
        return None
    return path


def _git_blob(value: str) -> bool:
    return len(value) == 40 and all(char in "0123456789abcdef" for char in value.lower())


def _git_blob_at(path: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "hash-object", str(path)],
            cwd=path.parent,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""
