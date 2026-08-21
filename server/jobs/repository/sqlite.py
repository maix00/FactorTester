"""Low-frequency SQLite repository for canonical research-job facts."""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import orjson

import settings as Settings
from tools.data.sqlite.db import connect_sqlite

from ..assurance import BackendAssuranceValidator, canonical_hash
from ..models import JobRecord
from ..states import JobStatus, NON_TERMINAL_STATUSES, TERMINAL_STATUSES, require_transition
from .artifacts import JobArtifactImplementation
from .custom_analyses import JobCustomAnalysisImplementation
from .detail import JobDetailQueryImplementation
from .queries import JobQueryImplementation
from .schema import ensure_job_schema
from .terminal import evaluate_terminal_assurance


def _dumps(value: Any) -> str:
    return orjson.dumps(
        value,
        option=orjson.OPT_SORT_KEYS | orjson.OPT_SERIALIZE_NUMPY,
    ).decode()


def _loads(value: str | None, default: Any = None) -> Any:
    return orjson.loads(value) if value else default


class JobRepository(
    JobQueryImplementation,
    JobDetailQueryImplementation,
    JobArtifactImplementation,
    JobCustomAnalysisImplementation,
):
    """Own the durable queue and terminal metadata, never live progress."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        assurance_validator: BackendAssuranceValidator | None = None,
    ) -> None:
        self.db_path = Path(db_path or Settings.CACHE_DB_PATH)
        self.assurance_validator = assurance_validator or BackendAssuranceValidator()
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        conn = connect_sqlite(self.db_path, foreign_keys=True)
        conn.execute("PRAGMA journal_mode = WAL")
        if not self._schema_ready:
            with self._schema_lock:
                if not self._schema_ready:
                    try:
                        self._ensure_schema(conn)
                    except Exception:
                        conn.close()
                        raise
                    self._schema_ready = True
        return conn

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """Commit or roll back one repository operation, then close its handle."""
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def _ensure_schema(conn: sqlite3.Connection) -> None:
        ensure_job_schema(conn)

    def ensure_schema(self) -> None:
        with self._connection():
            pass

    def create(self, record: JobRecord) -> JobRecord:
        if record.status in TERMINAL_STATUSES:
            raise ValueError("terminal jobs must use transition")
        if record.terminal_assurance is not None:
            raise ValueError("terminal assurance is repository-owned")
        now = record.created_at or time.time()
        job_spec_raw = orjson.dumps(record.job_spec, option=orjson.OPT_SORT_KEYS)
        with self._connection() as conn:
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
                        job_role, parent_job_id, supplemental_kind,
                        supplemental_identity, source_artifact_hash,
                        retry_of, attempt, step_mode, retention_mode,
                        deployment_id, service_port, source_revision, runner_path,
                        job_spec_json, job_spec_hash, run_spec_hash,
                        entitlement_json, execution_plan_json,
                        execution_plan_hash, queued_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.job_id,
                        record.run_id,
                        record.owner,
                        record.workspace_id,
                        record.kind,
                        record.status.value,
                        record.job_role,
                        record.parent_job_id,
                        record.supplemental_kind,
                        record.supplemental_identity,
                        record.source_artifact_hash,
                        record.retry_of,
                        max(1, record.attempt),
                        int(record.step_mode),
                        record.retention_mode,
                        record.deployment_id,
                        max(0, int(record.service_port or 0)),
                        record.source_revision,
                        record.runner_path,
                        job_spec_raw.decode(),
                        hashlib.sha256(job_spec_raw).hexdigest(),
                        record.run_spec_hash,
                        _dumps(record.entitlement.to_dict()),
                        _dumps(record.execution_plan) if record.execution_plan is not None else None,
                        canonical_hash(record.execution_plan) if record.execution_plan is not None else "",
                        now if record.status is JobStatus.QUEUED else None,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                if record.step_mode and "research_jobs.owner" in str(exc):
                    raise ValueError("step job already active") from exc
                raise
        return self.require(record.job_id, owner=record.owner)

    def create_or_load_supplemental(self, record: JobRecord) -> tuple[JobRecord, bool]:
        """Create one idempotent supplemental JobAttempt in research_jobs."""
        if record.job_role != "supplemental":
            raise ValueError("supplemental job_role is required")
        if record.status is not JobStatus.QUEUED:
            raise ValueError("supplemental jobs must enter the queue directly")
        try:
            return self.create(record), True
        except sqlite3.IntegrityError:
            with self._connection() as conn:
                row = conn.execute(
                    """
                    SELECT * FROM research_jobs
                    WHERE job_role='supplemental' AND parent_job_id=?
                      AND supplemental_kind=? AND supplemental_identity=?
                      AND source_artifact_hash=?
                      AND status IN ('submitted', 'planning', 'queued', 'running', 'paused')
                    """,
                    (record.parent_job_id, record.supplemental_kind,
                     record.supplemental_identity, record.source_artifact_hash),
                ).fetchone()
            existing = self._record(row)
            if existing is None:
                raise
            return existing, False

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
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM research_jobs WHERE job_id=?",
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
            if target in TERMINAL_STATUSES:
                stored_result = (
                    result_summary
                    if result_summary is not None
                    else _loads(row["result_summary_json"])
                )
                stored_error = (
                    error if error is not None else _loads(row["error_json"])
                )
                stored_exitcode = (
                    int(worker_exitcode)
                    if worker_exitcode is not None
                    else row["worker_exitcode"]
                )
                assurance = evaluate_terminal_assurance(
                    conn,
                    row=row,
                    terminal_status=target.value,
                    result_summary=stored_result,
                    error=stored_error,
                    worker_exitcode=stored_exitcode,
                    job_spec=dict(_loads(row["job_spec_json"], {})),
                    execution_plan=_loads(row["execution_plan_json"]),
                    validator=self.assurance_validator,
                )
                assignments.append("terminal_assurance_json=?")
                values.append(_dumps(assurance.to_dict()))
            values.append(str(job_id))
            updated = conn.execute(
                f"""
                UPDATE research_jobs
                SET {', '.join(assignments)}
                WHERE job_id=?
                RETURNING *
                """,
                values,
            ).fetchone()
            if target is JobStatus.RUNNING:
                conn.execute(
                    "DELETE FROM user_job_pins WHERE owner=? AND job_id=?",
                    (str(row["owner"]), str(job_id)),
                )
        record = self._record(updated)
        if record is None:
            raise RuntimeError("job transition returned no record")
        if target in TERMINAL_STATUSES:
            from server.services.transient_factor_sources import (
                cleanup_for_terminal_job,
            )

            cleanup_for_terminal_job(self, record)
        return record

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
        with self._connection() as conn:
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
        with self._connection() as conn:
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
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM research_jobs WHERE job_id=? AND owner=?",
                (str(job_id), str(owner)),
            ).fetchone()
            if row is None:
                raise KeyError("research job not found")
            status = JobStatus(row["status"])
            if status in TERMINAL_STATUSES:
                record = self._record(row)
                if record is None:
                    raise RuntimeError("terminal job could not be loaded")
                from server.services.transient_factor_sources import (
                    cleanup_for_terminal_job,
                )

                cleanup_for_terminal_job(self, record)
                return record
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
                assurance = evaluate_terminal_assurance(
                    conn,
                    row=row,
                    terminal_status=JobStatus.CANCELLED.value,
                    result_summary=_loads(row["result_summary_json"]),
                    error=_loads(row["error_json"]),
                    worker_exitcode=row["worker_exitcode"],
                    job_spec=dict(_loads(row["job_spec_json"], {})),
                    execution_plan=_loads(row["execution_plan_json"]),
                    validator=self.assurance_validator,
                )
                assignments.append("terminal_assurance_json=?")
                values.append(_dumps(assurance.to_dict()))
            values.extend([str(job_id), str(owner)])
            updated = conn.execute(
                f"""
                UPDATE research_jobs
                SET {', '.join(assignments)}
                WHERE job_id=? AND owner=?
                RETURNING *
                """,
                values,
            ).fetchone()
            if status in NON_TERMINAL_STATUSES:
                conn.execute(
                    "DELETE FROM user_job_pins WHERE owner=? AND job_id=?",
                    (str(owner), str(job_id)),
                )
        record = self._record(updated)
        if record is None:
            raise RuntimeError("cancel request returned no record")
        if record.status in TERMINAL_STATUSES:
            from server.services.transient_factor_sources import (
                cleanup_for_terminal_job,
            )

            cleanup_for_terminal_job(self, record)
        return record

    def pin(self, job_id: str, *, owner: str) -> JobRecord:
        now = time.time()
        with self._connection() as conn:
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
        with self._connection() as conn:
            conn.execute("DELETE FROM user_job_pins WHERE owner=?", (str(owner),))

    def pinned_job_id(self, *, owner: str) -> str:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT job_id FROM user_job_pins WHERE owner=?",
                (str(owner),),
            ).fetchone()
        return str(row["job_id"]) if row is not None else ""
