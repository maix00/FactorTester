"""SQLite persistence for client-owned local runs and their outbox."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Iterator

from .local_run_payloads import (
    HASH_PATTERN,
    JOB_ID_PATTERN,
    artifact_manifest as normalize_artifact_manifest,
    as_object,
    canonical_json,
    public_value,
    server_artifacts,
    server_projection,
    sha256_json,
)
from .local_run_schema import ensure_local_run_schema
from .schema import connect_catalog, ensure_catalog_schema


STATUSES = {
    "queued", "planning", "running", "succeeded", "failed", "cancelled", "blocked",
}


class LocalRunStore:
    """Persist local execution facts and their retryable sync operations."""

    def __init__(self, client_root: str | Path) -> None:
        self.client_root = Path(client_root).expanduser().resolve()
        self.database_path = self.client_root / "catalog" / "catalog.sqlite"

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = connect_catalog(self.database_path)
        try:
            ensure_catalog_schema(connection)
            ensure_local_run_schema(connection)
            yield connection
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()

    def record(
        self,
        *,
        local_job_id: str,
        owner_ref: str,
        requirements: list[dict[str, Any]],
        title: str = "",
        kind: str = "test",
        status: str = "queued",
        workspace_id: str = "",
        profile_ref: str = "",
        configuration: dict[str, Any] | None = None,
        summary: dict[str, Any] | None = None,
        source_snapshot: dict[str, Any] | None = None,
        artifact_manifest: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        job_id = str(local_job_id or "").strip()
        owner = str(owner_ref or "").strip()
        selected_status = str(status or "queued").strip().lower()
        if not JOB_ID_PATTERN.fullmatch(job_id):
            raise ValueError(
                "local_job_id must contain only letters, numbers, dot, underscore or hyphen"
            )
        if not owner:
            raise ValueError("owner_ref is required")
        if selected_status not in STATUSES:
            raise ValueError("local run status is unsupported")
        if not isinstance(requirements, list) or not requirements:
            raise ValueError("requirements must be a non-empty list")
        configuration = as_object(configuration, "configuration")
        summary = as_object(summary, "summary")
        source_snapshot = as_object(source_snapshot, "source_snapshot")
        artifacts = normalize_artifact_manifest(artifact_manifest)
        now = time.time()
        public_configuration = public_value(configuration)
        public_summary = public_value(summary)
        public_source_snapshot = public_value(source_snapshot)
        with self.connection() as connection:
            old = connection.execute(
                "SELECT created_at FROM local_runs WHERE local_job_id=?",
                (job_id,),
            ).fetchone()
            old_artifacts = {
                str(item["name"]): dict(item)
                for item in connection.execute(
                    "SELECT * FROM local_run_artifacts WHERE local_job_id=?",
                    (job_id,),
                ).fetchall()
            }
            for item in artifacts:
                previous = old_artifacts.get(item["name"])
                if not previous:
                    continue
                same_file = (
                    int(previous.get("size_bytes") or 0) == item["size_bytes"]
                    and str(previous.get("content_hash") or "").lower()
                    == item["content_hash"]
                )
                if same_file and previous.get("upload_state") in {"pending", "uploaded"}:
                    item["upload_state"] = str(previous["upload_state"])
            created_at = float(old[0]) if old is not None else now
            identity = {
                "local_job_id": job_id,
                "owner_ref": owner,
                "title": str(title or ""),
                "kind": str(kind or "test"),
                "status": selected_status,
                "workspace_id": str(workspace_id or ""),
                "profile_ref": str(profile_ref or ""),
                "requirements": requirements,
                "configuration": public_configuration,
                "summary": public_summary,
                "source_snapshot": public_source_snapshot,
                "artifact_manifest": server_artifacts(artifacts),
            }
            metadata_hash = sha256_json(identity)
            record = {
                **identity,
                "created_at": created_at,
                "updated_at": now,
                "execution_mode": "local",
                "metadata_hash": metadata_hash,
                "artifact_manifest": artifacts,
            }
            payload = server_projection(record)
            operation_id = sha256_json({
                "local_job_id": job_id,
                "kind": "sync_summary",
                "hash": metadata_hash,
            })
            connection.execute(
                """
                INSERT INTO local_runs(
                    local_job_id, owner_ref, title, kind, status, execution_mode,
                    workspace_id, profile_ref, created_at, updated_at,
                    requirements_json, configuration_json, summary_json, source_snapshot_json,
                    metadata_hash, sync_state, last_sync_error
                ) VALUES (?, ?, ?, ?, ?, 'local', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', '')
                ON CONFLICT(local_job_id) DO UPDATE SET
                    owner_ref=excluded.owner_ref, title=excluded.title,
                    kind=excluded.kind, status=excluded.status,
                    execution_mode='local', workspace_id=excluded.workspace_id,
                    profile_ref=excluded.profile_ref, updated_at=excluded.updated_at,
                    requirements_json=excluded.requirements_json,
                    configuration_json=excluded.configuration_json,
                    summary_json=excluded.summary_json,
                    source_snapshot_json=excluded.source_snapshot_json,
                    metadata_hash=excluded.metadata_hash,
                    sync_state='pending', last_sync_error=''
                """,
                (
                    job_id, owner, str(title or ""), str(kind or "test"),
                    selected_status, str(workspace_id or ""), str(profile_ref or ""),
                    created_at, now, canonical_json(requirements),
                    canonical_json(configuration), canonical_json(summary),
                    canonical_json(source_snapshot), metadata_hash,
                ),
            )
            connection.execute(
                "DELETE FROM local_run_artifacts WHERE local_job_id=?", (job_id,)
            )
            connection.executemany(
                """
                INSERT INTO local_run_artifacts(
                    local_job_id, name, file_name, role, content_type, size_bytes,
                    content_hash, local_path, upload_state, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [(
                    job_id, item["name"], item["file_name"], item["role"],
                    item["content_type"], item["size_bytes"], item["content_hash"],
                    item["local_path"], item["upload_state"], now,
                ) for item in artifacts],
            )
            connection.execute(
                """
                INSERT INTO local_run_outbox(
                    operation_id, local_job_id, operation_kind, payload_json,
                    projection_hash, state, attempts, created_at, updated_at, last_error
                ) VALUES (?, ?, 'sync_summary', ?, ?, 'pending', 0, ?, ?, '')
                ON CONFLICT(local_job_id, operation_kind, projection_hash) DO UPDATE SET
                    operation_id=excluded.operation_id, payload_json=excluded.payload_json,
                    state='pending', updated_at=excluded.updated_at, last_error=''
                """,
                (operation_id, job_id, canonical_json(payload), metadata_hash, now, now),
            )
        return self.get(job_id) or record

    def enqueue_artifact_upload(self, local_job_id: str, name: str) -> dict[str, Any]:
        """Record explicit upload intent; bytes still move through 7997 later."""
        job_id = str(local_job_id or "").strip()
        artifact_name = str(name or "").strip()
        if not JOB_ID_PATTERN.fullmatch(job_id) or not artifact_name:
            raise ValueError("local_job_id and artifact name are required")
        now = time.time()
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM local_run_artifacts WHERE local_job_id=? AND name=?",
                (job_id, artifact_name),
            ).fetchone()
            if row is None:
                raise KeyError("local artifact does not exist")
            artifact = dict(row)
            if not artifact["local_path"]:
                raise ValueError("local artifact has no file path")
            digest = str(artifact.get("content_hash") or "").strip().lower()
            if not HASH_PATTERN.fullmatch(digest):
                raise ValueError(
                    "local artifact must have a complete SHA-256 hash before upload"
                )
            payload = {
                "schema_version": 1,
                "local_job_id": job_id,
                "name": artifact_name,
                "file_name": artifact["file_name"],
                "role": artifact["role"],
                "content_type": artifact["content_type"],
                "size_bytes": int(artifact["size_bytes"]),
                "content_hash": digest,
                "raw_artifacts_remote": True,
            }
            projection_hash = sha256_json(payload)
            operation_id = sha256_json({
                "local_job_id": job_id,
                "kind": "upload_artifact",
                "hash": projection_hash,
            })
            connection.execute(
                "UPDATE local_run_artifacts SET upload_state='pending', updated_at=? "
                "WHERE local_job_id=? AND name=?",
                (now, job_id, artifact_name),
            )
            connection.execute(
                """
                INSERT INTO local_run_outbox(
                    operation_id, local_job_id, operation_kind, payload_json,
                    projection_hash, state, attempts, created_at, updated_at, last_error
                ) VALUES (?, ?, 'upload_artifact', ?, ?, 'pending', 0, ?, ?, '')
                ON CONFLICT(local_job_id, operation_kind, projection_hash) DO UPDATE SET
                    operation_id=excluded.operation_id, payload_json=excluded.payload_json,
                    state='pending', updated_at=excluded.updated_at, last_error=''
                """,
                (operation_id, job_id, canonical_json(payload), projection_hash, now, now),
            )
        return payload

    def get(self, local_job_id: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM local_runs WHERE local_job_id=?", (str(local_job_id),)
            ).fetchone()
            if row is None:
                return None
            return self._row(connection, row)

    def list(self, owner_ref: str, *, limit: int = 100) -> list[dict[str, Any]]:
        bounded = max(1, min(500, int(limit)))
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM local_runs WHERE owner_ref=? "
                "ORDER BY updated_at DESC, local_job_id LIMIT ?",
                (str(owner_ref or ""), bounded),
            ).fetchall()
            return [self._row(connection, row) for row in rows]

    def pending_outbox(self, *, limit: int = 50) -> list[dict[str, Any]]:
        bounded = max(1, min(200, int(limit)))
        with self.connection() as connection:
            self._reopen_stale_claims(connection)
            rows = connection.execute(
                "SELECT * FROM local_run_outbox WHERE state IN ('pending','error') "
                "ORDER BY created_at, operation_id LIMIT ?",
                (bounded,),
            ).fetchall()
        return [self._outbox_row(row) for row in rows]

    def claim_outbox(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """Atomically claim retryable operations for one sync worker."""
        bounded = max(1, min(200, int(limit)))
        with self.connection() as connection:
            now = time.time()
            self._reopen_stale_claims(connection, now=now)
            rows = connection.execute(
                "SELECT * FROM local_run_outbox WHERE state IN ('pending','error') "
                "ORDER BY created_at, operation_id LIMIT ?",
                (bounded,),
            ).fetchall()
            result = []
            for row in rows:
                operation_id = str(row["operation_id"])
                connection.execute(
                    "UPDATE local_run_outbox SET state='sending', attempts=attempts+1, "
                    "updated_at=?, last_error='' WHERE operation_id=? "
                    "AND state IN ('pending','error')",
                    (now, operation_id),
                )
                claimed = dict(row)
                claimed["state"] = "sending"
                claimed["attempts"] = int(claimed.get("attempts") or 0) + 1
                claimed["updated_at"] = now
                claimed["payload"] = json.loads(claimed.pop("payload_json") or "{}")
                result.append(claimed)
            return result

    def mark_artifact_uploaded(
        self, local_job_id: str, name: str, transfer_id: str,
    ) -> None:
        """Record the server acknowledgement in the client catalog."""
        if not str(transfer_id or "").strip():
            raise ValueError("local artifact transfer id is required")
        with self.connection() as connection:
            now = time.time()
            updated = connection.execute(
                "UPDATE local_run_artifacts SET upload_state='uploaded', updated_at=? "
                "WHERE local_job_id=? AND name=?",
                (now, str(local_job_id or ""), str(name or "")),
            )
            if updated.rowcount != 1:
                raise KeyError("local artifact does not exist")
            connection.execute(
                "UPDATE local_runs SET updated_at=? WHERE local_job_id=?",
                (now, str(local_job_id or "")),
            )

    def mark_outbox(self, operation_id: str, *, state: str, error: str = "") -> None:
        selected = str(state or "").strip()
        if selected not in {"pending", "sending", "synced", "error"}:
            raise ValueError("outbox state is unsupported")
        with self.connection() as connection:
            attempts = ", attempts=attempts+1" if selected == "sending" else ""
            connection.execute(
                f"UPDATE local_run_outbox SET state=?{attempts}, updated_at=?, "
                "last_error=? WHERE operation_id=?",
                (selected, time.time(), str(error or "")[:1000], str(operation_id or "")),
            )
            row = connection.execute(
                "SELECT local_job_id FROM local_run_outbox WHERE operation_id=?",
                (str(operation_id or ""),),
            ).fetchone()
            if row is not None:
                self._refresh_run_sync_state(
                    connection, str(row[0]), selected=selected, error=str(error or ""),
                )

    @staticmethod
    def _reopen_stale_claims(
        connection: sqlite3.Connection, *, now: float | None = None,
    ) -> None:
        current = time.time() if now is None else now
        connection.execute(
            "UPDATE local_run_outbox SET state='error', "
            "last_error='previous sync attempt expired', updated_at=? "
            "WHERE state='sending' AND updated_at < ?",
            (current, current - 300),
        )

    @staticmethod
    def _refresh_run_sync_state(
        connection: sqlite3.Connection,
        local_job_id: str,
        *,
        selected: str,
        error: str,
    ) -> None:
        """Keep the run state pending while any sibling outbox row remains."""
        rows = connection.execute(
            "SELECT state, last_error FROM local_run_outbox WHERE local_job_id=?",
            (local_job_id,),
        ).fetchall()
        states = {str(row[0] or "") for row in rows}
        if "error" in states:
            sync_state = "error"
            last_error = next(
                (str(row[1] or "") for row in rows if str(row[0] or "") == "error"),
                error[:1000],
            )
        elif states.intersection({"pending", "sending"}):
            sync_state = "pending"
            last_error = ""
        elif states and states == {"synced"}:
            sync_state = "synced"
            last_error = ""
        else:
            sync_state = "pending" if selected != "synced" else "synced"
            last_error = error[:1000] if selected != "synced" else ""
        connection.execute(
            "UPDATE local_runs SET sync_state=?, last_sync_error=?, updated_at=? "
            "WHERE local_job_id=?",
            (sync_state, last_error, time.time(), local_job_id),
        )

    @staticmethod
    def _outbox_row(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["payload"] = json.loads(value.pop("payload_json") or "{}")
        return value

    @staticmethod
    def _row(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        for key in (
            "requirements_json", "configuration_json", "summary_json",
            "source_snapshot_json",
        ):
            raw = value.pop(key, "{}")
            try:
                value[key.removesuffix("_json")] = json.loads(raw or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                value[key.removesuffix("_json")] = {}
        artifacts = connection.execute(
            "SELECT * FROM local_run_artifacts WHERE local_job_id=? ORDER BY role, name",
            (value["local_job_id"],),
        ).fetchall()
        value["artifact_manifest"] = [dict(item) for item in artifacts]
        value["execution_mode"] = "local"
        value["server_projection"] = server_projection(value)
        return value


__all__ = ["LocalRunStore"]
