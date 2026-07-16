"""Durable SQLite store for async test job metadata.

The live in-process registry owns running workers and SSE fanout. This module
owns canonical job metadata/status/snapshot so closed pages, process restarts,
and later UI sessions can reason about prior jobs without depending on
``page_runtime``.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

import orjson

import settings as Settings
from tools.data.sqlite.db import connect_sqlite


EVENT_RETAIN_LIMIT = 500


@dataclass(frozen=True)
class DurableJobRecord:
    job_id: str
    kind: str
    run_token: str
    run_id: str
    workspace_id: str
    owner: str
    initiator_page_uuid: str
    initiator_view_uuid: str
    lifecycle_policy: str
    status: str
    cancel_reason: str
    cancel_requested_at: float | None
    request_digest: str
    run_spec_hash: str
    run_spec: dict[str, Any]
    retry_of: str
    attempt: int
    execution_mode: str
    runner_path: str
    worker_pid: int | None
    worker_exitcode: int | None
    dispatcher_pid: int | None
    created_at: float
    started_at: float | None
    finished_at: float | None
    latest_progress: dict[str, Any] | None
    manifest: dict[str, Any] | None
    result: dict[str, Any] | None
    error: dict[str, Any] | None
    checkpoint: dict[str, Any] | None

    @property
    def page_uuid(self) -> str:
        return self.initiator_page_uuid

    def summary(self) -> dict[str, Any]:
        latest_event = None
        if self.latest_progress:
            latest_event = {
                "event": self.latest_progress.get("event"),
                "data": self.latest_progress.get("data") or {},
                "seq": self.latest_progress.get("seq"),
                "created_at": self.latest_progress.get("created_at"),
            }
        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "run_token": self.run_token,
            "run_id": self.run_id,
            "workspace_id": self.workspace_id,
            "page_uuid": self.initiator_page_uuid,
            "initiator_page_uuid": self.initiator_page_uuid,
            "view_uuid": self.initiator_view_uuid,
            "lifecycle_policy": self.lifecycle_policy,
            "status": self.status,
            "cancel_reason": self.cancel_reason,
            "cancel_requested": self.cancel_requested_at is not None,
            "cancel_requested_at": self.cancel_requested_at,
            "request_digest": self.request_digest,
            "run_spec_hash": self.run_spec_hash,
            "retry_of": self.retry_of,
            "attempt": self.attempt,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "execution_mode": self.execution_mode,
            "runner_path": self.runner_path or None,
            "worker_pid": self.worker_pid,
            "worker_exitcode": self.worker_exitcode,
            "dispatcher_pid": self.dispatcher_pid,
            "latest_event": latest_event,
            "latest_progress": self.latest_progress,
            "manifest": self.manifest,
            "has_result": self.result is not None,
            "has_error": self.error is not None,
            "checkpoint": self.checkpoint,
            "durable": True,
        }


def _json_dumps(value: Any) -> str:
    return orjson.dumps(value, option=orjson.OPT_SORT_KEYS | orjson.OPT_SERIALIZE_NUMPY).decode()


def _json_loads(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return orjson.loads(raw)
    except Exception:
        return None


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS test_jobs (
            job_id TEXT PRIMARY KEY,
            owner TEXT NOT NULL,
            workspace_context TEXT NOT NULL DEFAULT '',
            workspace_id TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL,
            run_token TEXT NOT NULL,
            run_id TEXT NOT NULL DEFAULT '',
            initiator_page_uuid TEXT NOT NULL,
            initiator_view_uuid TEXT NOT NULL DEFAULT '',
            lifecycle_policy TEXT NOT NULL DEFAULT 'durable',
            status TEXT NOT NULL,
            cancel_reason TEXT NOT NULL DEFAULT '',
            cancel_requested_at REAL,
            request_digest TEXT NOT NULL,
            run_spec_hash TEXT NOT NULL,
            run_spec_json TEXT NOT NULL,
            retry_of TEXT NOT NULL DEFAULT '',
            attempt INTEGER NOT NULL DEFAULT 1,
            execution_mode TEXT NOT NULL DEFAULT 'thread',
            runner_path TEXT NOT NULL DEFAULT '',
            worker_pid INTEGER,
            worker_exitcode INTEGER,
            created_at REAL NOT NULL,
            started_at REAL,
            finished_at REAL,
            latest_progress_json TEXT,
            manifest_json TEXT,
            result_json TEXT,
            error_json TEXT,
            checkpoint_json TEXT,
            updated_at REAL NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_test_jobs_owner_status ON test_jobs(owner, status, updated_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_test_jobs_owner_context ON test_jobs(owner, kind, workspace_context, run_spec_hash)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_test_jobs_page ON test_jobs(initiator_page_uuid, status)")
    columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(test_jobs)").fetchall()}
    additions = {
        "workspace_id": "TEXT NOT NULL DEFAULT ''",
        "run_id": "TEXT NOT NULL DEFAULT ''",
        "initiator_view_uuid": "TEXT NOT NULL DEFAULT ''",
        "lifecycle_policy": "TEXT NOT NULL DEFAULT 'durable'",
        "cancel_requested_at": "REAL",
        "dispatcher_pid": "INTEGER",
        "checkpoint_json": "TEXT",
    }
    for name, declaration in additions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE test_jobs ADD COLUMN {name} {declaration}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_test_jobs_run ON test_jobs(owner, run_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_test_jobs_workspace ON test_jobs(owner, workspace_id, created_at)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS test_job_process_slots (
            slot INTEGER PRIMARY KEY,
            job_id TEXT NOT NULL,
            dispatcher_pid INTEGER NOT NULL,
            leased_until REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS test_job_events (
            job_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            event TEXT NOT NULL,
            data_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            PRIMARY KEY (job_id, seq)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS test_job_artifacts (
            job_id TEXT NOT NULL,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            content_type TEXT NOT NULL,
            payload_json TEXT,
            content_hash TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            created_at REAL NOT NULL,
            expires_at REAL,
            PRIMARY KEY (job_id, name)
        )
        """
    )


def ensure_test_job_store() -> str:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
    reconcile_orphaned_jobs()
    return str(Settings.CACHE_DB_PATH)


def run_spec_hash(snapshot_bytes: bytes) -> str:
    snapshot = orjson.loads(snapshot_bytes)
    if isinstance(snapshot, dict):
        snapshot = dict(snapshot)
        for key in ("page_uuid", "view_uuid", "run_token", "job_id", "_retry_of", "retry_of", "_attempt", "attempt"):
            snapshot.pop(key, None)
        snapshot_bytes = orjson.dumps(snapshot, option=orjson.OPT_SORT_KEYS)
    return hashlib.sha256(snapshot_bytes).hexdigest()


def create_job_record(*, job: Any, workspace_context: str = "", retry_of: str = "", attempt: int = 1) -> None:
    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO test_jobs (
                job_id, owner, workspace_context, workspace_id, kind, run_token, run_id,
                initiator_page_uuid, initiator_view_uuid, lifecycle_policy,
                status, cancel_reason, request_digest, run_spec_hash, run_spec_json,
                retry_of, attempt, execution_mode, runner_path, worker_pid, worker_exitcode,
                created_at, started_at, finished_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, '', NULL, NULL, ?, NULL, NULL, ?)
            """,
            (
                job.job_id,
                job.owner,
                workspace_context,
                job.workspace_id,
                job.kind,
                job.run_token,
                job.run_id,
                job.page_uuid,
                job.view_uuid,
                job.lifecycle_policy,
                job.status,
                job.request_digest,
                run_spec_hash(job.request_snapshot_bytes),
                job.request_snapshot_bytes.decode(),
                retry_of,
                int(attempt or 1),
                job.execution_mode,
                job.created_at,
                now,
            ),
        )


def update_job_record(job: Any, *, cancel_reason: str = "") -> None:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        conn.execute(
            """
            UPDATE test_jobs
            SET status = ?, cancel_reason = COALESCE(NULLIF(?, ''), cancel_reason),
                execution_mode = ?, runner_path = ?, worker_pid = ?, worker_exitcode = ?,
                dispatcher_pid = ?, started_at = ?, finished_at = ?, result_json = ?, error_json = ?,
                checkpoint_json = ?,
                updated_at = ?
            WHERE job_id = ?
            """,
            (
                job.status,
                cancel_reason,
                job.execution_mode,
                job.runner_path or "",
                job.worker_pid,
                job.worker_exitcode,
                getattr(job, "dispatcher_pid", None),
                job.started_at,
                job.finished_at,
                _json_dumps(job.result) if job.result is not None else None,
                _json_dumps(job.error) if job.error is not None else None,
                _json_dumps(getattr(job, "checkpoint", None)) if getattr(job, "checkpoint", None) is not None else None,
                time.time(),
                job.job_id,
            ),
        )


def record_event(job: Any, event: Any) -> None:
    data = event.to_dict()
    latest_progress = None
    manifest = None
    if event.event in {"start", "progress", "signal_progress", "runtime_info", "worker", "execution_mode", "step", "result", "error"}:
        latest_progress = {"seq": event.seq, "event": event.event, "data": event.data, "created_at": event.created_at}
    if event.event == "activity_manifest":
        manifest = {"seq": event.seq, "event": event.event, "data": event.data, "created_at": event.created_at}
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        conn.execute(
            """
            INSERT OR REPLACE INTO test_job_events (job_id, seq, event, data_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (job.job_id, event.seq, event.event, _json_dumps(data["data"]), event.created_at),
        )
        if latest_progress is not None:
            conn.execute(
                "UPDATE test_jobs SET latest_progress_json = ?, updated_at = ? WHERE job_id = ?",
                (_json_dumps(latest_progress), time.time(), job.job_id),
            )
        if manifest is not None:
            conn.execute(
                "UPDATE test_jobs SET manifest_json = ?, updated_at = ? WHERE job_id = ?",
                (_json_dumps(manifest), time.time(), job.job_id),
            )
        row = conn.execute("SELECT MAX(seq) AS max_seq FROM test_job_events WHERE job_id = ?", (job.job_id,)).fetchone()
        max_seq = int(row["max_seq"] or 0)
        cutoff = max_seq - EVENT_RETAIN_LIMIT
        if cutoff > 0:
            conn.execute("DELETE FROM test_job_events WHERE job_id = ? AND seq <= ?", (job.job_id, cutoff))


def _record_from_row(row: sqlite3.Row | None) -> DurableJobRecord | None:
    if row is None:
        return None
    return DurableJobRecord(
        job_id=str(row["job_id"]),
        kind=str(row["kind"]),
        run_token=str(row["run_token"]),
        run_id=str(row["run_id"] or row["run_token"]),
        workspace_id=str(row["workspace_id"] or ""),
        owner=str(row["owner"]),
        initiator_page_uuid=str(row["initiator_page_uuid"]),
        initiator_view_uuid=str(row["initiator_view_uuid"] or row["initiator_page_uuid"]),
        lifecycle_policy=str(row["lifecycle_policy"] or "durable"),
        status=str(row["status"]),
        cancel_reason=str(row["cancel_reason"] or ""),
        cancel_requested_at=row["cancel_requested_at"],
        request_digest=str(row["request_digest"]),
        run_spec_hash=str(row["run_spec_hash"]),
        run_spec=_json_loads(row["run_spec_json"]) or {},
        retry_of=str(row["retry_of"] or ""),
        attempt=int(row["attempt"] or 1),
        execution_mode=str(row["execution_mode"] or "thread"),
        runner_path=str(row["runner_path"] or ""),
        worker_pid=row["worker_pid"],
        worker_exitcode=row["worker_exitcode"],
        dispatcher_pid=row["dispatcher_pid"],
        created_at=float(row["created_at"]),
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        latest_progress=_json_loads(row["latest_progress_json"]),
        manifest=_json_loads(row["manifest_json"]),
        result=_json_loads(row["result_json"]),
        error=_json_loads(row["error_json"]),
        checkpoint=_json_loads(row["checkpoint_json"]),
    )


def _pid_is_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError):
        return False
    return True


def reconcile_orphaned_jobs(*, unclaimed_grace_seconds: float = 30.0) -> int:
    """Fail jobs whose dispatching Flask process disappeared.

    A live dispatcher in another Flask worker is preserved. Newly-created jobs
    receive a short grace before a missing dispatcher is treated as a crash.
    """
    now = time.time()
    changed = 0
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            "SELECT job_id, status, dispatcher_pid, created_at FROM test_jobs WHERE status IN ('queued', 'running')"
        ).fetchall()
        for row in rows:
            dispatcher_pid = row["dispatcher_pid"]
            if dispatcher_pid and _pid_is_alive(int(dispatcher_pid)):
                continue
            if not dispatcher_pid and now - float(row["created_at"]) < float(unclaimed_grace_seconds):
                continue
            error = {
                "success": False,
                "error": "job dispatcher exited before completion",
                "worker_crash": True,
                "dispatcher_pid": dispatcher_pid,
            }
            conn.execute(
                """
                UPDATE test_jobs
                SET status = 'failed', finished_at = ?, error_json = ?, updated_at = ?
                WHERE job_id = ? AND status IN ('queued', 'running')
                """,
                (now, _json_dumps(error), now, str(row["job_id"])),
            )
            changed += 1
    return changed


def request_cancel(*, job_id: str, owner: str, reason: str) -> tuple[bool, str]:
    """Persist a cancellation request visible to every Flask worker."""
    now = time.time()
    reason = str(reason or "explicit_cancel")
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT owner, status FROM test_jobs WHERE job_id = ?",
            (str(job_id),),
        ).fetchone()
        if row is None:
            raise KeyError("test job not found")
        if str(row["owner"]) != str(owner):
            raise PermissionError("无权取消其他用户的测试任务")
        status = str(row["status"])
        if status in {"succeeded", "failed", "cancelled", "expired"}:
            return False, status
        if status in {"queued", "paused"}:
            error = {
                "success": False,
                "error": "test job cancelled before start",
                "cancelled": True,
                "cancel_reason": reason,
            }
            conn.execute(
                """
                UPDATE test_jobs
                SET status = 'cancelled', cancel_reason = ?, cancel_requested_at = ?,
                    finished_at = ?, error_json = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (reason, now, now, _json_dumps(error), now, str(job_id)),
            )
            return True, "cancelled"
        conn.execute(
            """
            UPDATE test_jobs
            SET cancel_reason = ?, cancel_requested_at = ?, updated_at = ?
            WHERE job_id = ?
            """,
            (reason, now, now, str(job_id)),
        )
        return True, status


def cancel_request(job_id: str) -> str:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT cancel_reason, cancel_requested_at FROM test_jobs WHERE job_id = ?",
            (str(job_id),),
        ).fetchone()
    if row is None or row["cancel_requested_at"] is None:
        return ""
    return str(row["cancel_reason"] or "explicit_cancel")


def acquire_process_slot(
    *, job_id: str, dispatcher_pid: int, limit: int, lease_seconds: float = 5.0,
) -> int | None:
    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM test_job_process_slots WHERE leased_until < ?", (now,))
        occupied = {
            int(row["slot"])
            for row in conn.execute("SELECT slot FROM test_job_process_slots").fetchall()
        }
        slot = next((value for value in range(max(1, int(limit))) if value not in occupied), None)
        if slot is None:
            return None
        conn.execute(
            "INSERT INTO test_job_process_slots(slot, job_id, dispatcher_pid, leased_until) VALUES (?, ?, ?, ?)",
            (slot, str(job_id), int(dispatcher_pid), now + float(lease_seconds)),
        )
        return slot


def renew_process_slot(*, slot: int, job_id: str, lease_seconds: float = 5.0) -> bool:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        cursor = conn.execute(
            "UPDATE test_job_process_slots SET leased_until = ? WHERE slot = ? AND job_id = ?",
            (time.time() + float(lease_seconds), int(slot), str(job_id)),
        )
        return cursor.rowcount == 1


def release_process_slot(*, slot: int, job_id: str) -> None:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        conn.execute(
            "DELETE FROM test_job_process_slots WHERE slot = ? AND job_id = ?",
            (int(slot), str(job_id)),
        )


def load_job(job_id: str) -> DurableJobRecord | None:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        row = conn.execute("SELECT * FROM test_jobs WHERE job_id = ?", (str(job_id),)).fetchone()
    return _record_from_row(row)


def list_jobs(
    *,
    owner: str,
    kind: str = "",
    workspace_id: str = "",
    run_id: str = "",
    statuses: set[str] | None = None,
    limit: int = 20,
) -> list[DurableJobRecord]:
    clauses = ["owner = ?"]
    args: list[Any] = [owner]
    if kind:
        clauses.append("kind = ?")
        args.append(kind)
    if workspace_id:
        clauses.append("workspace_id = ?")
        args.append(workspace_id)
    if run_id:
        clauses.append("run_id = ?")
        args.append(run_id)
    if statuses is not None:
        placeholders = ", ".join("?" for _ in statuses)
        clauses.append(f"status IN ({placeholders})")
        args.extend(sorted(statuses))
    args.append(max(1, int(limit)))
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            f"""
            SELECT *
            FROM test_jobs
            WHERE {' AND '.join(clauses)}
            ORDER BY updated_at DESC, created_at DESC
            LIMIT ?
            """,
            args,
        ).fetchall()
    return [record for row in rows if (record := _record_from_row(row)) is not None]


def load_events_after(job_id: str, seq: int = 0) -> list[dict[str, Any]]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT seq, event, data_json, created_at
            FROM test_job_events
            WHERE job_id = ? AND seq > ?
            ORDER BY seq
            """,
            (str(job_id), int(seq or 0)),
        ).fetchall()
    return [
        {
            "seq": int(row["seq"]),
            "event": str(row["event"]),
            "data": _json_loads(row["data_json"]) or {},
            "created_at": float(row["created_at"]),
        }
        for row in rows
    ]


def event_bounds(job_id: str) -> tuple[int, int]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT MIN(seq) AS oldest, MAX(seq) AS newest FROM test_job_events WHERE job_id = ?",
            (str(job_id),),
        ).fetchone()
    return int(row["oldest"] or 0), int(row["newest"] or 0)


def expire_jobs(*, ttl_seconds: int) -> int:
    cutoff = time.time() - max(60, int(ttl_seconds))
    now = time.time()
    error = _json_dumps({
        "success": False,
        "error": "test job result expired",
        "expired": True,
        "ttl_seconds": max(60, int(ttl_seconds)),
    })
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT job_id FROM test_jobs
            WHERE status IN ('succeeded', 'failed', 'cancelled', 'paused')
              AND finished_at IS NOT NULL AND finished_at < ?
            """,
            (cutoff,),
        ).fetchall()
        job_ids = [str(row["job_id"]) for row in rows]
        if not job_ids:
            return 0
        placeholders = ",".join("?" for _ in job_ids)
        conn.execute(
            f"""
            UPDATE test_jobs
            SET status = 'expired', result_json = NULL, checkpoint_json = NULL,
                error_json = ?, updated_at = ?
            WHERE job_id IN ({placeholders})
            """,
            (error, now, *job_ids),
        )
        conn.execute(
            f"""
            UPDATE test_job_artifacts
            SET status = 'expired', payload_json = NULL, expires_at = ?
            WHERE job_id IN ({placeholders})
            """,
            (now, *job_ids),
        )
        return len(job_ids)


def store_artifact(*, job_id: str, name: str, value: Any) -> None:
    raw = orjson.dumps(value, option=orjson.OPT_SORT_KEYS | orjson.OPT_SERIALIZE_NUMPY)
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO test_job_artifacts (
                job_id, name, status, content_type, payload_json,
                content_hash, size_bytes, created_at, expires_at
            ) VALUES (?, ?, 'active', 'application/json', ?, ?, ?, ?, NULL)
            ON CONFLICT(job_id, name) DO UPDATE SET
                status = 'active', payload_json = excluded.payload_json,
                content_hash = excluded.content_hash,
                size_bytes = excluded.size_bytes, created_at = excluded.created_at,
                expires_at = NULL
            """,
            (
                str(job_id),
                str(name),
                raw.decode(),
                hashlib.sha256(raw).hexdigest(),
                len(raw),
                time.time(),
            ),
        )


def load_artifact(*, job_id: str, name: str) -> dict[str, Any] | None:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        row = conn.execute(
            """
            SELECT * FROM test_job_artifacts
            WHERE job_id = ? AND name = ?
            """,
            (str(job_id), str(name)),
        ).fetchone()
    if row is None:
        return None
    return {
        "job_id": str(row["job_id"]),
        "name": str(row["name"]),
        "status": str(row["status"]),
        "content_type": str(row["content_type"]),
        "content_hash": str(row["content_hash"]),
        "size_bytes": int(row["size_bytes"]),
        "created_at": float(row["created_at"]),
        "expires_at": row["expires_at"],
        "value": _json_loads(row["payload_json"]),
    }
