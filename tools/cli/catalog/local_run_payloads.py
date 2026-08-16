"""Canonical and summary-only payloads for local-run synchronization."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
ARTIFACT_NAME_PATTERN = re.compile(r"^[^/\\\x00]{1,512}$")
CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
PRIVATE_KEYS = {
    "absolute_path", "content_base64", "local_path", "source_code",
    "source_path", "workspace_root", "receipt_path", "storage_path",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def as_object(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return dict(value)


def artifact_manifest(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("artifact_manifest must be a list")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("each artifact manifest item must be an object")
        name = str(item.get("name") or "").strip()
        if not _safe_name(name) or name in seen:
            raise ValueError("artifact name is invalid")
        seen.add(name)
        file_name = str(item.get("file_name") or name).strip()
        if not _safe_name(file_name):
            raise ValueError("artifact file_name is invalid")
        try:
            size = int(item.get("size_bytes") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("artifact size_bytes must be an integer") from exc
        if size < 0:
            raise ValueError("artifact size_bytes must not be negative")
        digest = str(item.get("content_hash") or "").strip().lower()
        if digest and not HASH_PATTERN.fullmatch(digest.removeprefix("sha256:")):
            raise ValueError("artifact content_hash must be SHA-256")
        result.append({
            "name": name,
            "file_name": file_name,
            "role": "input" if str(
                item.get("role") or item.get("artifact_role") or "output"
            ) == "input" else "output",
            "content_type": str(
                item.get("content_type") or "application/octet-stream"
            ),
            "size_bytes": size,
            "content_hash": digest.removeprefix("sha256:"),
            # Kept in client SQLite only; ``server_projection`` strips it.
            "local_path": str(item.get("local_path") or ""),
            "upload_state": str(item.get("upload_state") or "local_only"),
        })
    return result


def server_projection(record: dict[str, Any]) -> dict[str, Any]:
    """Return the summary-only payload allowed to cross the server boundary."""
    artifacts = server_artifacts(record.get("artifact_manifest") or [])
    return {
        "schema_version": 1,
        "local_job_id": record["local_job_id"],
        "title": record.get("title") or "",
        "kind": record.get("kind") or "test",
        "status": record.get("status") or "queued",
        "execution_mode": "local",
        "workspace_id": record.get("workspace_id") or "",
        "profile_ref": record.get("profile_ref") or "",
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "configuration": public_value(record.get("configuration") or {}),
        "summary": public_value(record.get("summary") or {}),
        "source_snapshot": public_value(record.get("source_snapshot") or {}),
        "requirements": record.get("requirements") or [],
        "artifact_manifest": artifacts,
        "raw_artifacts_remote": False,
        "explicit_uploads_only": True,
        "metadata_hash": record.get("metadata_hash") or "",
    }


def server_artifacts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    artifacts = []
    for item in value:
        if not isinstance(item, dict):
            continue
        projected = {
            key: item.get(key)
            for key in (
                "name", "file_name", "role", "content_type", "size_bytes",
                "content_hash", "upload_state",
            )
        }
        projected["raw_artifact_available"] = bool(
            item.get("upload_state") == "uploaded"
        )
        artifacts.append(projected)
    return artifacts


def public_value(value: Any, *, key: str = "") -> Any:
    """Remove local source/path material from a server projection."""
    normalized = str(key or "").strip().lower()
    if normalized in PRIVATE_KEYS:
        return None
    if isinstance(value, dict):
        result = {}
        for name, raw in value.items():
            if str(name).strip().lower() in PRIVATE_KEYS:
                continue
            projected = public_value(raw, key=str(name))
            if projected is not None:
                result[str(name)] = projected
        return result
    if isinstance(value, list):
        return [
            projected for item in value
            for projected in [public_value(item)]
            if projected is not None
        ]
    return value


def _safe_name(value: str) -> bool:
    return bool(
        value and value not in {".", ".."}
        and ARTIFACT_NAME_PATTERN.fullmatch(value)
        and not CONTROL_CHARACTERS.search(value)
    )


__all__ = [
    "ARTIFACT_NAME_PATTERN", "HASH_PATTERN", "JOB_ID_PATTERN",
    "artifact_manifest", "as_object", "canonical_json", "public_value",
    "server_artifacts", "server_projection", "sha256_json",
]
