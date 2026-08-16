"""Manager-local, summary-only projection of client-owned local runs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
from typing import Any

from tools.data.sqlite.db import connect_sqlite


_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_PRIVATE_KEYS = {
    "absolute_path", "content_base64", "local_path", "owner_ref",
    "receipt_path", "source_code", "source_path", "storage_path",
    "storage_transfer_id", "workspace_root",
}
_ARTIFACT_NAME = re.compile(r"^[^/\\\x00]{1,512}$")
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


class LocalRunProjection:
    """Keep local-run metadata without importing local files or source code."""

    def __init__(self, path: str | Path, *, server_id: str) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.server_id = str(server_id or "local").strip() or "local"
        with self._connection() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS local_runs (
                    principal TEXT NOT NULL,
                    local_job_id TEXT NOT NULL,
                    projection_hash TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (principal, local_job_id)
                )
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS local_runs_updated
                ON local_runs(updated_at DESC, principal, local_job_id)
                """
            )

    def _connection(self) -> sqlite3.Connection:
        return connect_sqlite(self.path, timeout=5.0)

    def upsert(self, principal: str, payload: dict[str, Any]) -> dict[str, Any]:
        owner = str(principal or "").strip()
        if not owner:
            raise ValueError("local-run owner is required")
        value = _sanitize_payload(payload)
        job_id = str(value.get("local_job_id") or "").strip()
        if not _JOB_ID.fullmatch(job_id):
            raise ValueError("local_job_id is invalid")
        updated_at = _timestamp(value.get("updated_at")) or time.time()
        with self._connection() as db:
            current = db.execute(
                "SELECT updated_at, projection_hash, payload_json FROM local_runs WHERE principal=? AND local_job_id=?",
                (owner, job_id),
            ).fetchone()
            _retain_uploaded_artifacts(
                value, current[2] if current is not None else "",
            )
            projection_hash = _projection_hash(value)
            value["metadata_hash"] = projection_hash
            encoded = json.dumps(
                value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            )
            if current is not None:
                old_updated = float(current[0] or 0)
                if updated_at < old_updated:
                    existing = self.get(owner, job_id)
                    if existing is not None:
                        return existing
                    return self._record(owner, value)
                if str(current[1] or "") == projection_hash:
                    existing = self.get(owner, job_id)
                    if existing is not None:
                        return existing
                    return self._record(owner, value)
            db.execute(
                """
                INSERT INTO local_runs(
                    principal, local_job_id, projection_hash, updated_at, payload_json
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(principal, local_job_id) DO UPDATE SET
                    projection_hash=excluded.projection_hash,
                    updated_at=excluded.updated_at,
                    payload_json=excluded.payload_json
                """,
                (owner, job_id, projection_hash, updated_at, encoded),
            )
        existing = self.get(owner, job_id)
        if existing is not None:
            return existing
        return self._record(owner, value)

    def get(self, principal: str, local_job_id: str) -> dict[str, Any] | None:
        with self._connection() as db:
            row = db.execute(
                "SELECT payload_json FROM local_runs WHERE principal=? AND local_job_id=?",
                (str(principal or "").strip(), str(local_job_id or "").strip()),
            ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row[0] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return self._record(str(principal or "").strip(), payload)

    def get_any(self, local_job_id: str) -> dict[str, Any] | None:
        with self._connection() as db:
            row = db.execute(
                "SELECT principal, payload_json FROM local_runs WHERE local_job_id=? ORDER BY updated_at DESC LIMIT 1",
                (str(local_job_id or "").strip(),),
            ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row[1] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return self._record(str(row[0] or ""), payload)

    def page(
        self,
        principal: str,
        *,
        page: int = 1,
        limit: int = 20,
    ) -> dict[str, Any]:
        return self._page_where(
            "principal=?", (str(principal or "").strip(),), page=page, limit=limit,
        )

    def page_all(self, *, page: int = 1, limit: int = 20) -> dict[str, Any]:
        return self._page_where("1=1", (), page=page, limit=limit)

    def _page_where(
        self,
        where: str,
        args: tuple[Any, ...],
        *,
        page: int,
        limit: int,
    ) -> dict[str, Any]:
        selected_page = max(1, int(page))
        bounded = max(1, min(100, int(limit)))
        with self._connection() as db:
            total = int(db.execute(
                f"SELECT COUNT(*) FROM local_runs WHERE {where}", args,
            ).fetchone()[0])
            rows = db.execute(
                f"SELECT principal, payload_json FROM local_runs WHERE {where} "
                "ORDER BY updated_at DESC, local_job_id LIMIT ? OFFSET ?",
                (*args, bounded, (selected_page - 1) * bounded),
            ).fetchall()
        jobs = []
        for row in rows:
            try:
                payload = json.loads(row[1] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            jobs.append(self._record(str(row[0] or ""), payload)["job"])
        total_pages = max(1, (total + bounded - 1) // bounded)
        return {
            "success": True,
            "jobs": jobs,
            "page": selected_page,
            "page_size": bounded,
            "total": total,
            "total_pages": total_pages,
            "has_more": selected_page < total_pages,
            "next_cursor": None,
        }

    def mark_artifact_uploaded(
        self,
        principal: str,
        local_job_id: str,
        name: str,
        transfer_id: str,
    ) -> dict[str, Any]:
        owner = str(principal or "").strip()
        job_id = str(local_job_id or "").strip()
        artifact_name = str(name or "").strip()
        uploaded_transfer = str(transfer_id or "").strip()
        if not owner or not _JOB_ID.fullmatch(job_id) or not uploaded_transfer:
            raise ValueError("local artifact upload fields are invalid")
        with self._connection() as db:
            row = db.execute(
                "SELECT payload_json FROM local_runs WHERE principal=? AND local_job_id=?",
                (owner, job_id),
            ).fetchone()
            if row is None:
                raise KeyError("local run was not found")
            try:
                payload = _sanitize_payload(
                    json.loads(row[0] or "{}"), preserve_uploaded=True,
                )
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError("local run projection is invalid") from exc
            found = False
            for item in payload.get("artifact_manifest") or []:
                if str(item.get("name") or "") == artifact_name:
                    item.update({
                        "upload_state": "uploaded",
                        "raw_artifact_available": True,
                        "storage_transfer_id": uploaded_transfer,
                    })
                    found = True
            if not found:
                raise KeyError("local artifact was not found")
            payload["updated_at"] = time.time()
            payload["metadata_hash"] = _projection_hash(payload)
            db.execute(
                """
                UPDATE local_runs
                SET projection_hash=?, updated_at=?, payload_json=?
                WHERE principal=? AND local_job_id=?
                """,
                (
                    payload["metadata_hash"], payload["updated_at"],
                    json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                    owner, job_id,
                ),
            )
        result = self.get(owner, job_id)
        if result is None:
            raise KeyError("local run was not found")
        return result

    def _record(self, principal: str, payload: dict[str, Any]) -> dict[str, Any]:
        value = _sanitize_payload(payload, preserve_uploaded=True)
        artifacts = []
        for item in value.get("artifact_manifest") or []:
            if not isinstance(item, dict):
                continue
            artifact = dict(item)
            artifact["state"] = (
                "active" if artifact.get("upload_state") == "uploaded"
                else "local_only"
            )
            artifacts.append(artifact)
        output = [item for item in artifacts if item.get("role") != "input"]
        inputs = [item for item in artifacts if item.get("role") == "input"]
        storage = {
            "artifact_count": len(artifacts),
            "output_artifact_count": len(output),
            "input_artifact_count": len(inputs),
            "artifact_bytes": sum(int(item.get("size_bytes") or 0) for item in artifacts),
            "output_artifact_bytes": sum(int(item.get("size_bytes") or 0) for item in output),
            "input_artifact_bytes": sum(int(item.get("size_bytes") or 0) for item in inputs),
            "remote_artifact_count": sum(
                1 for item in artifacts if item.get("upload_state") == "uploaded"
            ),
        }
        remote_artifacts = storage["remote_artifact_count"] > 0
        job = {
            "job_id": value["local_job_id"],
            "task_name": value.get("title") or "",
            "owner": principal,
            "title": value.get("title") or "",
            "kind": value.get("kind") or "test",
            "status": value.get("status") or "queued",
            "updated_at": value.get("updated_at") or time.time(),
            "created_at": value.get("created_at") or value.get("updated_at") or time.time(),
            "execution_mode": "local",
            "local_run": True,
            "raw_artifacts_remote": remote_artifacts,
            "port": 0,
            "service_port": 0,
            # The execution origin is the client, even when this Manager
            # receives the summary projection.  The Manager id remains in the
            # SQLite projection path and transfer records, not in the user
            # facing server-origin column.
            "server_id": "local",
            "profile_ref": value.get("profile_ref") or "",
            "profile": value.get("profile_ref") or "",
            "workspace_id": value.get("workspace_id") or "",
            "artifact_count": len(artifacts),
            "artifact_bytes": storage["artifact_bytes"],
            "output_artifact_count": storage["output_artifact_count"],
            "output_artifact_bytes": storage["output_artifact_bytes"],
            "input_artifact_count": storage["input_artifact_count"],
            "input_artifact_bytes": storage["input_artifact_bytes"],
        }
        detail = {
            "job": job,
            "task_detail": {
                "job": job,
                "artifacts": artifacts,
                "input_artifacts": inputs,
                "storage": storage,
                "configuration": value.get("configuration") or {},
                "results": value.get("summary") or {},
                "result_summary": value.get("summary") or {},
                "local_run": True,
                "raw_artifacts_remote": remote_artifacts,
                "source_snapshot": value.get("source_snapshot") or {},
                "requirements": value.get("requirements") or [],
            },
            "result_summary": value.get("summary") or {},
            "execution_mode": "local",
            "local_run": True,
            "raw_artifacts_remote": remote_artifacts,
            "port": 0,
        }
        return {"principal": principal, "payload": value, **detail}


def _sanitize_payload(
    payload: dict[str, Any], *, preserve_uploaded: bool = False,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("local-run payload must be an object")
    value = _public_value(payload)
    value.pop("owner_ref", None)
    artifacts = []
    original_artifacts = payload.get("artifact_manifest") or []
    for index, raw in enumerate(value.get("artifact_manifest") or []):
        if not isinstance(raw, dict):
            continue
        name = _safe_artifact_name(raw.get("name"), fallback="")
        if not name:
            raise ValueError("artifact name is invalid")
        try:
            size = int(raw.get("size_bytes") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("artifact size_bytes must be an integer") from exc
        if size < 0:
            raise ValueError("artifact size_bytes must not be negative")
        digest = str(raw.get("content_hash") or "").lower().removeprefix("sha256:")
        if digest and not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("artifact content_hash must be SHA-256")
        original = (
            original_artifacts[index]
            if index < len(original_artifacts)
            and isinstance(original_artifacts[index], dict)
            else {}
        )
        uploaded = bool(
            preserve_uploaded
            and original.get("upload_state") == "uploaded"
            and str(original.get("storage_transfer_id") or "").strip()
        )
        file_name = _safe_artifact_name(raw.get("file_name"), fallback=name)
        if not file_name:
            raise ValueError("artifact file_name is invalid")
        item = {
            "name": name,
            "file_name": file_name,
            "role": "input" if str(raw.get("role") or "output") == "input" else "output",
            "content_type": str(raw.get("content_type") or "application/octet-stream"),
            "size_bytes": size,
            "content_hash": digest,
            "upload_state": "uploaded" if uploaded else "local_only",
        }
        if uploaded:
            item["storage_transfer_id"] = str(original["storage_transfer_id"]).strip()
        artifacts.append(item)
    value["artifact_manifest"] = artifacts
    value["raw_artifacts_remote"] = False
    value["explicit_uploads_only"] = True
    return value


def _public_value(value: Any, *, key: str = "") -> Any:
    normalized = str(key or "").strip().lower()
    if normalized in _PRIVATE_KEYS:
        return None
    if isinstance(value, dict):
        result = {}
        for name, raw in value.items():
            if str(name).strip().lower() in _PRIVATE_KEYS:
                continue
            projected = _public_value(raw, key=str(name))
            if projected is not None:
                result[str(name)] = projected
        return result
    if isinstance(value, list):
        return [
            projected for item in value
            for projected in [_public_value(item)]
            if projected is not None
        ]
    return value


def _projection_hash(value: dict[str, Any]) -> str:
    projected = json.loads(json.dumps(value, ensure_ascii=False))
    projected.pop("metadata_hash", None)
    for item in projected.get("artifact_manifest") or []:
        if isinstance(item, dict):
            item.pop("storage_transfer_id", None)
    return hashlib.sha256(
        json.dumps(projected, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _retain_uploaded_artifacts(value: dict[str, Any], encoded_current: str) -> None:
    if not encoded_current:
        return
    try:
        current = json.loads(encoded_current)
    except (TypeError, ValueError, json.JSONDecodeError):
        return
    previous = {
        str(item.get("name") or ""): item
        for item in current.get("artifact_manifest") or []
        if isinstance(item, dict)
    }
    for item in value.get("artifact_manifest") or []:
        old = previous.get(str(item.get("name") or ""))
        if not old or old.get("upload_state") != "uploaded":
            continue
        same_file = (
            int(old.get("size_bytes") or 0) == int(item.get("size_bytes") or 0)
            and str(old.get("content_hash") or "") == str(item.get("content_hash") or "")
        )
        if same_file and old.get("storage_transfer_id"):
            item["upload_state"] = "uploaded"
            item["storage_transfer_id"] = old["storage_transfer_id"]


def _timestamp(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _safe_artifact_name(value: object, *, fallback: str) -> str:
    text = str(value or fallback).strip()
    if not text or text in {".", ".."}:
        return ""
    if not _ARTIFACT_NAME.fullmatch(text) or _CONTROL_CHARACTERS.search(text):
        return ""
    return text


__all__ = ["LocalRunProjection"]
