"""Read projections for canonical JobAttempt records."""

from __future__ import annotations

from collections.abc import Iterable
import sqlite3
from typing import Any

import orjson

from ..assurance import TerminalAssuranceSummary
from ..models import JobRecord, SchedulingEntitlement
from ..states import JobStatus


def _loads(value: str | None, default: Any = None) -> Any:
    return orjson.loads(value) if value else default


class JobQueryImplementation:
    """Keep JobRecord reconstruction and bounded queue queries in one owner."""

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
        return [
            record
            for row in rows
            if (record := self._record(row)) is not None
        ]

    def list_for_deployment(
        self,
        *,
        deployment_id: str,
        statuses: Iterable[JobStatus | str],
        limit: int = 500,
    ) -> list[JobRecord]:
        """Return scheduler-visible jobs without crossing the owner Interface."""
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
        return [
            record
            for row in rows
            if (record := self._record(row)) is not None
        ]

    def is_pinned(self, job_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM user_job_pins WHERE job_id=?",
                (str(job_id),),
            ).fetchone()
        return row is not None

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
            run_spec_hash=str(row["run_spec_hash"] or ""),
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
            terminal_assurance=TerminalAssuranceSummary.from_dict(
                _loads(row["terminal_assurance_json"])
            ),
            created_at=float(row["created_at"]),
            planned_at=row["planned_at"],
            approved_at=row["approved_at"],
            queued_at=row["queued_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            updated_at=float(row["updated_at"]),
        )
