"""Low-frequency SQLite repository for canonical research-job facts."""

from __future__ import annotations

import hashlib
import sqlite3
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import orjson

import settings as Settings
from tools.data.sqlite.db import connect_sqlite

from ..models import JobRecord, SchedulingEntitlement
from ..states import JobStatus, NON_TERMINAL_STATUSES, TERMINAL_STATUSES, require_transition


def _dumps(value: Any) -> str:
    return orjson.dumps(
        value,
        option=orjson.OPT_SORT_KEYS | orjson.OPT_SERIALIZE_NUMPY,
    ).decode()


def _loads(value: str | None, default: Any = None) -> Any:
    return orjson.loads(value) if value else default


class JobRepository:
    """Own the durable queue and terminal metadata, never live progress."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path or Settings.CACHE_DB_PATH)

    def _connect(self) -> sqlite3.Connection:
        conn = connect_sqlite(self.db_path, foreign_keys=True)
        conn.execute("PRAGMA journal_mode = WAL")
        self._ensure_schema(conn)
        return conn

    @staticmethod
    def _ensure_schema(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            DROP TABLE IF EXISTS test_job_events;
            DROP TABLE IF EXISTS test_job_process_slots;
            DROP TABLE IF EXISTS test_job_artifacts;
            DROP TABLE IF EXISTS test_jobs;
            DROP TABLE IF EXISTS research_view_leases;
            """
        )
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS research_jobs (
                job_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                owner TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                retry_of TEXT NOT NULL DEFAULT '',
                attempt INTEGER NOT NULL DEFAULT 1,
                step_mode INTEGER NOT NULL DEFAULT 0,
                retention_mode TEXT NOT NULL DEFAULT 'summary',
                deployment_id TEXT NOT NULL DEFAULT '',
                source_revision TEXT NOT NULL DEFAULT '',
                runner_path TEXT NOT NULL DEFAULT '',
                job_spec_json TEXT NOT NULL,
                job_spec_hash TEXT NOT NULL,
                worker_pid INTEGER,
                worker_exitcode INTEGER,
                cancel_requested_at REAL,
                cancel_reason TEXT NOT NULL DEFAULT '',
                entitlement_json TEXT NOT NULL,
                execution_plan_json TEXT,
                execution_plan_hash TEXT NOT NULL DEFAULT '',
                plan_notices_json TEXT NOT NULL DEFAULT '[]',
                result_summary_json TEXT,
                error_json TEXT,
                created_at REAL NOT NULL,
                planned_at REAL,
                approved_at REAL,
                queued_at REAL,
                started_at REAL,
                finished_at REAL,
                updated_at REAL NOT NULL,
                CHECK (status IN (
                    'submitted', 'planning', 'awaiting_confirmation', 'queued',
                    'running', 'paused', 'succeeded', 'failed', 'cancelled'
                )),
                CHECK (retention_mode IN ('summary', 'full'))
            );

            CREATE INDEX IF NOT EXISTS idx_research_jobs_owner_updated
                ON research_jobs(owner, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_research_jobs_workspace_updated
                ON research_jobs(owner, workspace_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_research_jobs_queue
                ON research_jobs(deployment_id, status, created_at);
            CREATE INDEX IF NOT EXISTS idx_research_jobs_run
                ON research_jobs(owner, run_id, created_at);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_research_jobs_one_active_step
                ON research_jobs(owner)
                WHERE step_mode=1 AND status IN (
                    'submitted', 'planning', 'awaiting_confirmation',
                    'queued', 'running', 'paused'
                );

            CREATE TABLE IF NOT EXISTS user_job_pins (
                owner TEXT PRIMARY KEY,
                job_id TEXT NOT NULL UNIQUE,
                pinned_at REAL NOT NULL,
                FOREIGN KEY (job_id) REFERENCES research_jobs(job_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS user_storage_policies (
                owner TEXT PRIMARY KEY,
                quota_bytes INTEGER NOT NULL,
                updated_at REAL NOT NULL,
                CHECK (quota_bytes >= 0)
            );

            CREATE TABLE IF NOT EXISTS research_job_artifacts (
                job_id TEXT NOT NULL,
                name TEXT NOT NULL,
                retention_mode TEXT NOT NULL,
                state TEXT NOT NULL,
                content_type TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                created_at REAL NOT NULL,
                deleted_at REAL,
                PRIMARY KEY (job_id, name),
                FOREIGN KEY (job_id) REFERENCES research_jobs(job_id) ON DELETE CASCADE,
                CHECK (retention_mode IN ('temporary', 'retained')),
                CHECK (state IN ('staging', 'active', 'deleting', 'deleted', 'failed')),
                CHECK (size_bytes >= 0)
            );
            """
        )

    def ensure_schema(self) -> None:
        with self._connect():
            pass

    def create(self, record: JobRecord) -> JobRecord:
        now = record.created_at or time.time()
        job_spec_raw = orjson.dumps(record.job_spec, option=orjson.OPT_SORT_KEYS)
        with self._connect() as conn:
            if record.step_mode:
                existing = conn.execute(
                    """
                    SELECT job_id FROM research_jobs
                    WHERE owner=? AND step_mode=1
                      AND status IN ('submitted', 'planning', 'awaiting_confirmation',
                                     'queued', 'running', 'paused')
                    LIMIT 1
                    """,
                    (record.owner,),
                ).fetchone()
                if existing is not None:
                    raise ValueError(
                        f"step job already active: {existing['job_id']}"
                    )
            try:
                conn.execute(
                    """
                    INSERT INTO research_jobs (
                        job_id, run_id, owner, workspace_id, kind, status,
                        retry_of, attempt, step_mode, retention_mode,
                        deployment_id, source_revision, runner_path,
                        job_spec_json, job_spec_hash,
                        entitlement_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.job_id,
                        record.run_id,
                        record.owner,
                        record.workspace_id,
                        record.kind,
                        record.status.value,
                        record.retry_of,
                        max(1, record.attempt),
                        int(record.step_mode),
                        record.retention_mode,
                        record.deployment_id,
                        record.source_revision,
                        record.runner_path,
                        job_spec_raw.decode(),
                        hashlib.sha256(job_spec_raw).hexdigest(),
                        _dumps(record.entitlement.to_dict()),
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                if record.step_mode and "research_jobs.owner" in str(exc):
                    raise ValueError("step job already active") from exc
                raise
        return self.require(record.job_id, owner=record.owner)

    def load(self, job_id: str, *, owner: str | None = None) -> JobRecord | None:
        clauses = ["job_id=?"]
        args: list[Any] = [str(job_id)]
        if owner is not None:
            clauses.append("owner=?")
            args.append(str(owner))
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT * FROM research_jobs WHERE {' AND '.join(clauses)}",
                args,
            ).fetchone()
        return self._record(row)

    def require(self, job_id: str, *, owner: str | None = None) -> JobRecord:
        record = self.load(job_id, owner=owner)
        if record is None:
            raise KeyError("research job not found")
        return record

    def list(
        self,
        *,
        owner: str,
        workspace_id: str = "",
        run_id: str = "",
        kind: str = "",
        statuses: Iterable[JobStatus | str] | None = None,
        limit: int = 20,
    ) -> list[JobRecord]:
        clauses = ["owner=?"]
        args: list[Any] = [str(owner)]
        for column, value in (
            ("workspace_id", workspace_id),
            ("run_id", run_id),
            ("kind", kind),
        ):
            if value:
                clauses.append(f"{column}=?")
                args.append(str(value))
        if statuses is not None:
            values = [JobStatus(value).value for value in statuses]
            if not values:
                return []
            clauses.append(f"status IN ({','.join('?' for _ in values)})")
            args.extend(values)
        args.append(min(200, max(1, int(limit))))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM research_jobs
                WHERE {' AND '.join(clauses)}
                ORDER BY updated_at DESC, created_at DESC
                LIMIT ?
                """,
                args,
            ).fetchall()
        return [record for row in rows if (record := self._record(row)) is not None]

    def list_for_deployment(
        self,
        *,
        deployment_id: str,
        statuses: Iterable[JobStatus | str],
        limit: int = 500,
    ) -> list[JobRecord]:
        """Return scheduler-visible jobs without crossing the owner API boundary."""
        values = [JobStatus(value).value for value in statuses]
        if not values:
            return []
        args: list[Any] = [str(deployment_id), *values]
        args.append(min(2000, max(1, int(limit))))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT jobs.*,
                       CASE WHEN pins.job_id IS NULL THEN 0 ELSE 1 END AS is_pinned
                FROM research_jobs AS jobs
                LEFT JOIN user_job_pins AS pins ON pins.job_id = jobs.job_id
                WHERE jobs.deployment_id=?
                  AND jobs.status IN ({','.join('?' for _ in values)})
                ORDER BY jobs.created_at, jobs.job_id
                LIMIT ?
                """,
                args,
            ).fetchall()
        return [record for row in rows if (record := self._record(row)) is not None]

    def is_pinned(self, job_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM user_job_pins WHERE job_id=?", (str(job_id),)
            ).fetchone()
        return row is not None

    def record_artifact(
        self,
        *,
        job_id: str,
        name: str,
        relative_path: str,
        content_type: str,
        content_hash: str,
        size_bytes: int,
        retention_mode: str = "retained",
    ) -> dict[str, Any]:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO research_job_artifacts (
                    job_id, name, retention_mode, state, content_type,
                    relative_path, content_hash, size_bytes, created_at
                ) VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?)
                ON CONFLICT(job_id, name) DO UPDATE SET
                    retention_mode=excluded.retention_mode,
                    state='active', content_type=excluded.content_type,
                    relative_path=excluded.relative_path,
                    content_hash=excluded.content_hash,
                    size_bytes=excluded.size_bytes, created_at=excluded.created_at,
                    deleted_at=NULL
                """,
                (
                    str(job_id), str(name), str(retention_mode), str(content_type),
                    str(relative_path), str(content_hash), max(0, int(size_bytes)), now,
                ),
            )
        return self.require_artifact(job_id=job_id, name=name)

    def load_artifact(self, *, job_id: str, name: str, owner: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT artifacts.* FROM research_job_artifacts AS artifacts
                JOIN research_jobs AS jobs ON jobs.job_id=artifacts.job_id
                WHERE artifacts.job_id=? AND artifacts.name=? AND jobs.owner=?
                """,
                (str(job_id), str(name), str(owner)),
            ).fetchone()
        return dict(row) if row is not None else None

    def require_artifact(self, *, job_id: str, name: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM research_job_artifacts WHERE job_id=? AND name=?",
                (str(job_id), str(name)),
            ).fetchone()
        if row is None:
            raise KeyError("research job artifact not found")
        return dict(row)

    def list_artifacts(self, *, job_id: str, owner: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT artifacts.* FROM research_job_artifacts AS artifacts
                JOIN research_jobs AS jobs ON jobs.job_id=artifacts.job_id
                WHERE artifacts.job_id=? AND jobs.owner=?
                ORDER BY artifacts.created_at, artifacts.name
                """,
                (str(job_id), str(owner)),
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_artifacts_deleted(self, *, job_id: str, owner: str) -> list[dict[str, Any]]:
        artifacts = self.list_artifacts(job_id=job_id, owner=owner)
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE research_job_artifacts SET state='deleted', deleted_at=?
                WHERE job_id=? AND job_id IN (
                    SELECT job_id FROM research_jobs WHERE owner=?
                ) AND state != 'deleted'
                """,
                (now, str(job_id), str(owner)),
            )
        return artifacts

    def mark_owner_artifacts_deleted(
        self, *, owner: str, workspace_id: str = "",
    ) -> list[dict[str, Any]]:
        clauses = ["jobs.owner=?", "artifacts.state != 'deleted'"]
        args: list[Any] = [str(owner)]
        if workspace_id:
            clauses.append("jobs.workspace_id=?")
            args.append(str(workspace_id))
        now = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                f"""
                SELECT artifacts.* FROM research_job_artifacts AS artifacts
                JOIN research_jobs AS jobs ON jobs.job_id=artifacts.job_id
                WHERE {' AND '.join(clauses)}
                ORDER BY artifacts.created_at, artifacts.job_id, artifacts.name
                """,
                args,
            ).fetchall()
            conn.execute(
                f"""
                UPDATE research_job_artifacts AS artifacts
                SET state='deleted', deleted_at=?
                WHERE EXISTS (
                    SELECT 1 FROM research_jobs AS jobs
                    WHERE jobs.job_id=artifacts.job_id
                      AND {' AND '.join(clauses)}
                )
                """,
                [now, *args],
            )
        return [dict(row) for row in rows]

    def storage_usage(self, *, owner: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(artifacts.size_bytes), 0) AS size_bytes
                FROM research_job_artifacts AS artifacts
                JOIN research_jobs AS jobs ON jobs.job_id=artifacts.job_id
                WHERE jobs.owner=? AND artifacts.state='active'
                """,
                (str(owner),),
            ).fetchone()
        return int(row["size_bytes"] or 0)

    def storage_quota(self, *, owner: str, default_bytes: int) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT quota_bytes FROM user_storage_policies WHERE owner=?",
                (str(owner),),
            ).fetchone()
        return int(row["quota_bytes"]) if row is not None else max(0, int(default_bytes))

    def set_storage_quota(self, *, owner: str, quota_bytes: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_storage_policies(owner, quota_bytes, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(owner) DO UPDATE SET
                    quota_bytes=excluded.quota_bytes, updated_at=excluded.updated_at
                """,
                (str(owner), max(0, int(quota_bytes)), time.time()),
            )

    def transition(
        self,
        job_id: str,
        target: JobStatus | str,
        *,
        expected: JobStatus | str | None = None,
        worker_pid: int | None = None,
        worker_exitcode: int | None = None,
        cancel_reason: str = "",
        result_summary: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> JobRecord:
        target = JobStatus(target)
        now = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT status, owner FROM research_jobs WHERE job_id=?",
                (str(job_id),),
            ).fetchone()
            if row is None:
                raise KeyError("research job not found")
            current = JobStatus(row["status"])
            if expected is not None and current != JobStatus(expected):
                raise RuntimeError(
                    f"job state changed: expected {JobStatus(expected).value}, found {current.value}"
                )
            require_transition(current, target)
            timestamps: dict[str, float] = {}
            if target is JobStatus.PLANNING:
                timestamps["planned_at"] = now
            elif target is JobStatus.AWAITING_CONFIRMATION:
                timestamps["planned_at"] = now
            elif target is JobStatus.QUEUED:
                timestamps["queued_at"] = now
            elif target is JobStatus.RUNNING:
                timestamps["started_at"] = now
            elif target in TERMINAL_STATUSES:
                timestamps["finished_at"] = now
            assignments = ["status=?", "updated_at=?"]
            values: list[Any] = [target.value, now]
            for column, value in timestamps.items():
                assignments.append(f"{column}=?")
                values.append(value)
            if worker_pid is not None:
                assignments.append("worker_pid=?")
                values.append(int(worker_pid))
            if worker_exitcode is not None:
                assignments.append("worker_exitcode=?")
                values.append(int(worker_exitcode))
            if cancel_reason:
                assignments.append("cancel_reason=?")
                values.append(str(cancel_reason))
            if result_summary is not None:
                assignments.append("result_summary_json=?")
                values.append(_dumps(result_summary))
            if error is not None:
                assignments.append("error_json=?")
                values.append(_dumps(error))
            values.append(str(job_id))
            conn.execute(
                f"UPDATE research_jobs SET {', '.join(assignments)} WHERE job_id=?",
                values,
            )
            if target is JobStatus.RUNNING:
                conn.execute(
                    "DELETE FROM user_job_pins WHERE owner=? AND job_id=?",
                    (str(row["owner"]), str(job_id)),
                )
        return self.require(job_id)

    def set_execution_plan(
        self,
        job_id: str,
        *,
        plan: dict[str, Any],
        notices: list[dict[str, Any]],
        requires_confirmation: bool,
    ) -> JobRecord:
        raw = orjson.dumps(plan, option=orjson.OPT_SORT_KEYS)
        target = (
            JobStatus.AWAITING_CONFIRMATION
            if requires_confirmation
            else JobStatus.QUEUED
        )
        now = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT status FROM research_jobs WHERE job_id=?",
                (str(job_id),),
            ).fetchone()
            if row is None:
                raise KeyError("research job not found")
            current = JobStatus(row["status"])
            if current is not JobStatus.PLANNING:
                raise RuntimeError(f"job is not planning: {current.value}")
            require_transition(current, target)
            conn.execute(
                """
                UPDATE research_jobs
                SET status=?, execution_plan_json=?, execution_plan_hash=?,
                    plan_notices_json=?, planned_at=?, queued_at=?, updated_at=?
                WHERE job_id=?
                """,
                (
                    target.value,
                    raw.decode(),
                    hashlib.sha256(raw).hexdigest(),
                    _dumps(notices),
                    now,
                    now if target is JobStatus.QUEUED else None,
                    now,
                    str(job_id),
                ),
            )
        return self.require(job_id)

    def approve_plan(self, job_id: str, *, owner: str) -> JobRecord:
        now = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                """
                UPDATE research_jobs
                SET status='queued', approved_at=?, queued_at=?, updated_at=?
                WHERE job_id=? AND owner=? AND status='awaiting_confirmation'
                """,
                (now, now, now, str(job_id), str(owner)),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("job is not awaiting confirmation")
        return self.require(job_id, owner=owner)

    def request_cancel(self, job_id: str, *, owner: str, reason: str) -> JobRecord:
        now = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT status FROM research_jobs WHERE job_id=? AND owner=?",
                (str(job_id), str(owner)),
            ).fetchone()
            if row is None:
                raise KeyError("research job not found")
            status = JobStatus(row["status"])
            if status in TERMINAL_STATUSES:
                return self.require(job_id, owner=owner)
            assignments = [
                "cancel_requested_at=?",
                "cancel_reason=?",
                "updated_at=?",
            ]
            values: list[Any] = [now, str(reason), now]
            if status in {
                JobStatus.SUBMITTED,
                JobStatus.PLANNING,
                JobStatus.AWAITING_CONFIRMATION,
                JobStatus.QUEUED,
                JobStatus.PAUSED,
            }:
                assignments.extend(["status='cancelled'", "finished_at=?"])
                values.append(now)
            values.extend([str(job_id), str(owner)])
            conn.execute(
                f"UPDATE research_jobs SET {', '.join(assignments)} WHERE job_id=? AND owner=?",
                values,
            )
            if status in NON_TERMINAL_STATUSES:
                conn.execute(
                    "DELETE FROM user_job_pins WHERE owner=? AND job_id=?",
                    (str(owner), str(job_id)),
                )
        return self.require(job_id, owner=owner)

    def pin(self, job_id: str, *, owner: str) -> JobRecord:
        now = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT status FROM research_jobs WHERE job_id=? AND owner=?",
                (str(job_id), str(owner)),
            ).fetchone()
            if row is None:
                raise KeyError("research job not found")
            if JobStatus(row["status"]) is not JobStatus.QUEUED:
                raise ValueError("only queued jobs can be pinned")
            conn.execute(
                """
                INSERT INTO user_job_pins(owner, job_id, pinned_at)
                VALUES (?, ?, ?)
                ON CONFLICT(owner) DO UPDATE SET
                    job_id=excluded.job_id, pinned_at=excluded.pinned_at
                """,
                (str(owner), str(job_id), now),
            )
        return self.require(job_id, owner=owner)

    def unpin(self, *, owner: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM user_job_pins WHERE owner=?", (str(owner),))

    def pinned_job_id(self, *, owner: str) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT job_id FROM user_job_pins WHERE owner=?",
                (str(owner),),
            ).fetchone()
        return str(row["job_id"]) if row is not None else ""

    @staticmethod
    def _record(row: sqlite3.Row | None) -> JobRecord | None:
        if row is None:
            return None
        return JobRecord(
            job_id=str(row["job_id"]),
            run_id=str(row["run_id"]),
            owner=str(row["owner"]),
            workspace_id=str(row["workspace_id"]),
            kind=str(row["kind"]),
            status=JobStatus(row["status"]),
            retry_of=str(row["retry_of"] or ""),
            attempt=int(row["attempt"] or 1),
            step_mode=bool(row["step_mode"]),
            retention_mode=str(row["retention_mode"]),
            deployment_id=str(row["deployment_id"] or ""),
            source_revision=str(row["source_revision"] or ""),
            runner_path=str(row["runner_path"] or ""),
            job_spec=dict(_loads(row["job_spec_json"], {})),
            job_spec_hash=str(row["job_spec_hash"]),
            worker_pid=row["worker_pid"],
            worker_exitcode=row["worker_exitcode"],
            cancel_requested_at=row["cancel_requested_at"],
            cancel_reason=str(row["cancel_reason"] or ""),
            entitlement=SchedulingEntitlement.from_dict(
                _loads(row["entitlement_json"], {})
            ),
            execution_plan=_loads(row["execution_plan_json"]),
            execution_plan_hash=str(row["execution_plan_hash"] or ""),
            plan_notices=list(_loads(row["plan_notices_json"], [])),
            result_summary=_loads(row["result_summary_json"]),
            error=_loads(row["error_json"]),
            created_at=float(row["created_at"]),
            planned_at=row["planned_at"],
            approved_at=row["approved_at"],
            queued_at=row["queued_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            updated_at=float(row["updated_at"]),
        )
