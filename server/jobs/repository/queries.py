"""Read projections for canonical JobAttempt records."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from typing import Any

import orjson

from ..assurance import TerminalAssuranceSummary
from ..models import JobRecord, SchedulingEntitlement
from ..states import TERMINAL_STATUSES, JobStatus


def _loads(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    try:
        return orjson.loads(value)
    except (orjson.JSONDecodeError, TypeError, ValueError):
        # A legacy job must remain inspectable even when one optional JSON
        # column was truncated or written by an older schema.
        return default


def _append_subject_clause(
    clauses: list[str], args: list[Any], *, table: str,
    object_kind: str, object_ref: str, owner_ref: str, alias: str,
) -> None:
    kind = str(object_kind or "").strip().lower()
    ref = str(object_ref or "").strip()
    owner = str(owner_ref or "").strip()
    name = str(alias or "").strip()
    if not kind and not ref and not owner and not name:
        return
    if kind not in {"family", "factor", "set"}:
        raise ValueError("object_kind must be family, factor, or set")
    if kind == "family" and owner and name:
        clauses.append(
            f"EXISTS (SELECT 1 FROM research_job_subjects AS subjects "
            f"WHERE subjects.job_id={table}.job_id "
            "AND subjects.object_kind=? AND subjects.owner_ref=? "
            "AND subjects.alias=?)"
        )
        args.extend((kind, owner, name))
        return
    if not ref:
        raise ValueError("object_ref is required")
    clauses.append(
        f"EXISTS (SELECT 1 FROM research_job_subjects AS subjects "
        f"WHERE subjects.job_id={table}.job_id "
        "AND subjects.object_kind=? AND subjects.object_ref=?)"
    )
    args.extend((kind, ref))


class JobQueryImplementation:
    """Keep JobRecord reconstruction and bounded queue queries in one owner."""

    def load(self, job_id: str, *, owner: str | None = None) -> JobRecord | None:
        clauses = ["job_id=?"]
        args: list[Any] = [str(job_id)]
        if owner is not None:
            clauses.append("owner=?")
            args.append(str(owner))
        with self._connection() as conn:
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

    def list_supplemental(
        self, *, parent_job_id: str, owner: str, search: str = "",
        statuses: Iterable[JobStatus | str] | None = None,
        limit: int = 20, offset: int = 0,
    ) -> list[JobRecord]:
        clauses = ["job_role='supplemental'", "parent_job_id=?", "owner=?"]
        args: list[Any] = [str(parent_job_id), str(owner)]
        if search:
            clauses.append(
                "(supplemental_kind LIKE ? OR job_id LIKE ? OR error_json LIKE ?)"
            )
            pattern = f"%{str(search).strip()}%"
            args.extend((pattern, pattern, pattern))
        normalized = [
            item.value if isinstance(item, JobStatus) else str(item)
            for item in (statuses or ())
        ]
        if normalized:
            clauses.append(f"status IN ({','.join('?' for _ in normalized)})")
            args.extend(normalized)
        args.extend((min(200, max(1, int(limit))), max(0, int(offset))))
        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM research_jobs
                WHERE {' AND '.join(clauses)}
                ORDER BY updated_at DESC, created_at DESC
                LIMIT ? OFFSET ?
                """,
                args,
            ).fetchall()
        return [record for row in rows if (record := self._record(row)) is not None]

    def count_supplemental(
        self, *, parent_job_id: str, owner: str, search: str = "",
        statuses: Iterable[JobStatus | str] | None = None,
    ) -> int:
        clauses = ["job_role='supplemental'", "parent_job_id=?", "owner=?"]
        args: list[Any] = [str(parent_job_id), str(owner)]
        if search:
            clauses.append(
                "(supplemental_kind LIKE ? OR job_id LIKE ? OR error_json LIKE ?)"
            )
            pattern = f"%{str(search).strip()}%"
            args.extend((pattern, pattern, pattern))
        normalized = [
            item.value if isinstance(item, JobStatus) else str(item)
            for item in (statuses or ())
        ]
        if normalized:
            clauses.append(f"status IN ({','.join('?' for _ in normalized)})")
            args.extend(normalized)
        with self._connection() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) AS total FROM research_jobs WHERE {' AND '.join(clauses)}",
                args,
            ).fetchone()
        return int(row["total"] or 0)

    def list(
        self,
        *,
        owner: str,
        workspace_id: str = "",
        run_id: str = "",
        kind: str = "",
        statuses: Iterable[JobStatus | str] | None = None,
        service_port: int | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[JobRecord]:
        clauses = ["owner=?", "job_role='primary'"]
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
        if service_port is not None:
            clauses.append("service_port=?")
            args.append(max(0, int(service_port)))
        args.append(min(200, max(1, int(limit))))
        args.append(max(0, int(offset)))
        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM research_jobs
                WHERE {' AND '.join(clauses)}
                ORDER BY updated_at DESC, created_at DESC
                LIMIT ? OFFSET ?
                """,
                args,
            ).fetchall()
        return [
            record
            for row in rows
            if (record := self._record(row)) is not None
        ]

    def has_run_attempts(self, *, owner: str, run_id: str) -> bool:
        """Return whether a Run has at least one durable JobAttempt."""
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM research_jobs
                WHERE owner=? AND run_id=? AND job_role='primary'
                LIMIT 1
                """,
                (str(owner), str(run_id)),
            ).fetchone()
        return row is not None

    def all_run_attempts_terminal(self, *, owner: str, run_id: str) -> bool:
        """Check Run terminality without materializing full JobSpecs."""
        terminal_values = tuple(status.value for status in TERMINAL_STATUSES)
        placeholders = ",".join("?" for _ in terminal_values)
        with self._connection() as conn:
            row = conn.execute(
                f"""
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN status IN ({placeholders})
                                THEN 0 ELSE 1 END) AS non_terminal
                FROM research_jobs
                WHERE owner=? AND run_id=? AND job_role='primary'
                """,
                (*terminal_values, str(owner), str(run_id)),
            ).fetchone()
        return bool(
            row is not None
            and int(row["total"] or 0) > 0
            and int(row["non_terminal"] or 0) == 0
        )

    def has_active_transient_scope(
        self,
        *,
        scope_id: str,
        owner: str = "",
    ) -> bool:
        """Check active JobSpecs without materializing their payloads."""
        scope_id = str(scope_id or "").strip()
        if not scope_id:
            return False
        terminal_values = tuple(status.value for status in TERMINAL_STATUSES)
        placeholders = ",".join("?" for _ in terminal_values)
        clauses = [
            "job_role='primary'",
            f"status NOT IN ({placeholders})",
            "instr(job_spec_json, ?) > 0",
        ]
        args: list[Any] = [*terminal_values, scope_id]
        if str(owner or "").strip():
            clauses.insert(0, "owner=?")
            args.insert(0, str(owner).strip())
        with self._connection() as conn:
            row = conn.execute(
                f"""
                SELECT 1 FROM research_jobs
                WHERE {' AND '.join(clauses)}
                LIMIT 1
                """,
                args,
            ).fetchone()
        return row is not None

    def list_with_metadata(
        self,
        *,
        owner: str = "",
        owners: Iterable[str] | None = None,
        workspace_id: str = "",
        run_id: str = "",
        kind: str = "",
        statuses: Iterable[JobStatus | str] | None = None,
        service_port: int | None = None,
        object_kind: str = "",
        object_ref: str = "",
        object_owner_ref: str = "",
        object_alias: str = "",
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return UI list rows with pin and active-artifact metadata."""
        normalized_owners = [str(item).strip() for item in (owners or ()) if str(item).strip()]
        if normalized_owners:
            clauses = [
                "jobs.job_role='primary'",
                f"jobs.owner IN ({','.join('?' for _ in normalized_owners)})"
            ]
            args: list[Any] = normalized_owners.copy()
        else:
            clauses = ["jobs.owner=?", "jobs.job_role='primary'"]
            args = [str(owner)]
        for column, value in (
            ("workspace_id", workspace_id),
            ("run_id", run_id),
            ("kind", kind),
        ):
            if value:
                clauses.append(f"jobs.{column}=?")
                args.append(str(value))
        if statuses is not None:
            values = [JobStatus(value).value for value in statuses]
            if not values:
                return []
            clauses.append(
                f"jobs.status IN ({','.join('?' for _ in values)})"
            )
            args.extend(values)
        if service_port is not None:
            clauses.append("jobs.service_port=?")
            args.append(max(0, int(service_port)))
        _append_subject_clause(
            clauses, args, table="jobs",
            object_kind=object_kind, object_ref=object_ref,
            owner_ref=object_owner_ref, alias=object_alias,
        )
        args.append(min(200, max(1, int(limit))))
        args.append(max(0, int(offset)))
        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT jobs.*,
                       CASE WHEN pins.job_id IS NULL
                            THEN 0 ELSE 1 END AS list_pinned,
                       COALESCE(artifacts.artifact_count, 0)
                           AS active_artifact_count,
                       COALESCE(artifacts.output_artifact_count, 0)
                           AS active_output_artifact_count,
                       COALESCE(artifacts.input_artifact_count, 0)
                           AS active_input_artifact_count,
                       COALESCE(artifacts.artifact_bytes, 0)
                           AS active_artifact_bytes,
                       COALESCE(artifacts.output_artifact_bytes, 0)
                           AS active_output_artifact_bytes,
                       COALESCE(artifacts.input_artifact_bytes, 0)
                           AS active_input_artifact_bytes,
                       COALESCE(supplementals.total, 0) AS supplemental_count,
                       COALESCE(supplementals.active, 0) AS supplemental_active_count,
                       COALESCE(supplementals.failed, 0) AS supplemental_failed_count,
                       supplementals.updated_at AS supplemental_updated_at,
                       MAX(jobs.updated_at, COALESCE(supplementals.updated_at, 0))
                           AS effective_updated_at
                FROM research_jobs AS jobs
                LEFT JOIN user_job_pins AS pins
                  ON pins.job_id=jobs.job_id AND pins.owner=jobs.owner
                LEFT JOIN (
                    SELECT job_id,
                           COUNT(*) AS artifact_count,
                           SUM(CASE WHEN artifact_role='output' THEN 1 ELSE 0 END)
                               AS output_artifact_count,
                           SUM(CASE WHEN artifact_role='input' THEN 1 ELSE 0 END)
                               AS input_artifact_count,
                           COALESCE(SUM(size_bytes), 0) AS artifact_bytes,
                           COALESCE(SUM(CASE WHEN artifact_role='output'
                                             THEN size_bytes ELSE 0 END), 0)
                               AS output_artifact_bytes,
                           COALESCE(SUM(CASE WHEN artifact_role='input'
                                             THEN size_bytes ELSE 0 END), 0)
                               AS input_artifact_bytes
                    FROM research_job_artifacts
                    WHERE state='active'
                    GROUP BY job_id
                ) AS artifacts ON artifacts.job_id=jobs.job_id
                LEFT JOIN (
                    SELECT parent_job_id, COUNT(*) AS total,
                           SUM(CASE WHEN status IN ('queued', 'running', 'paused')
                                    THEN 1 ELSE 0 END) AS active,
                           SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
                           MAX(updated_at) AS updated_at
                    FROM research_jobs
                    WHERE job_role='supplemental'
                    GROUP BY parent_job_id
                ) AS supplementals ON supplementals.parent_job_id=jobs.job_id
                WHERE {' AND '.join(clauses)}
                ORDER BY effective_updated_at DESC, jobs.created_at DESC
                LIMIT ? OFFSET ?
                """,
                args,
            ).fetchall()
        return [
            {
                "job": record,
                "pinned": bool(row["list_pinned"]),
                "artifact_count": int(row["active_artifact_count"]),
                "output_artifact_count": int(
                    row["active_output_artifact_count"] or 0
                ),
                "input_artifact_count": int(
                    row["active_input_artifact_count"] or 0
                ),
                "artifact_bytes": int(row["active_artifact_bytes"] or 0),
                "output_artifact_bytes": int(
                    row["active_output_artifact_bytes"] or 0
                ),
                "input_artifact_bytes": int(
                    row["active_input_artifact_bytes"] or 0
                ),
                "supplemental_count": int(row["supplemental_count"] or 0),
                "supplemental_active_count": int(
                    row["supplemental_active_count"] or 0
                ),
                "supplemental_failed_count": int(
                    row["supplemental_failed_count"] or 0
                ),
                "supplemental_updated_at": row["supplemental_updated_at"],
                "effective_updated_at": float(row["effective_updated_at"]),
            }
            for row in rows
            if (record := self._record(row)) is not None
        ]

    def count_with_metadata(
        self,
        *,
        owner: str = "",
        owners: Iterable[str] | None = None,
        workspace_id: str = "",
        run_id: str = "",
        kind: str = "",
        statuses: Iterable[JobStatus | str] | None = None,
        service_port: int | None = None,
        object_kind: str = "",
        object_ref: str = "",
        object_owner_ref: str = "",
        object_alias: str = "",
    ) -> int:
        """Count the same owner-scoped projection without loading job specs."""
        normalized_owners = [str(item).strip() for item in (owners or ()) if str(item).strip()]
        if normalized_owners:
            clauses = [
                "job_role='primary'",
                f"owner IN ({','.join('?' for _ in normalized_owners)})"
            ]
            args: list[Any] = normalized_owners.copy()
        else:
            clauses = ["owner=?", "job_role='primary'"]
            args = [str(owner)]
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
                return 0
            clauses.append(f"status IN ({','.join('?' for _ in values)})")
            args.extend(values)
        if service_port is not None:
            clauses.append("service_port=?")
            args.append(max(0, int(service_port)))
        _append_subject_clause(
            clauses, args, table="research_jobs",
            object_kind=object_kind, object_ref=object_ref,
            owner_ref=object_owner_ref, alias=object_alias,
        )
        with self._connection() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) AS total FROM research_jobs WHERE {' AND '.join(clauses)}",
                args,
            ).fetchone()
        return int(row["total"] or 0) if row is not None else 0

    def list_global_summaries(
        self,
        *,
        limit: int = 20,
        before_updated_at: float | None = None,
        before_job_id: str = "",
        include_artifacts: bool = False,
        object_kind: str = "",
        object_ref: str = "",
        object_owner_ref: str = "",
        object_alias: str = "",
    ) -> tuple[list[dict[str, Any]], bool]:
        """Return a bounded, non-sensitive all-owner administrative view."""
        bounded_limit = min(100, max(1, int(limit)))
        clauses: list[str] = ["research_jobs.job_role='primary'"]
        args: list[Any] = []
        _append_subject_clause(
            clauses, args, table="research_jobs",
            object_kind=object_kind, object_ref=object_ref,
            owner_ref=object_owner_ref, alias=object_alias,
        )
        if before_updated_at is not None:
            clauses.append(
                "(MAX(research_jobs.updated_at, "
                "COALESCE(supplemental_stats.updated_at, 0)), "
                "research_jobs.job_id) < (?, ?)"
            )
            args.extend((
                float(before_updated_at),
                str(before_job_id),
            ))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        args.append(bounded_limit + 1)
        artifact_select = ""
        artifact_join = ""
        supplemental_select = """
                       , COALESCE(supplemental_stats.total, 0)
                           AS supplemental_count,
                       COALESCE(supplemental_stats.active, 0)
                           AS supplemental_active_count,
                       COALESCE(supplemental_stats.failed, 0)
                           AS supplemental_failed_count,
                       supplemental_stats.updated_at AS supplemental_updated_at,
                       MAX(research_jobs.updated_at,
                           COALESCE(supplemental_stats.updated_at, 0))
                           AS effective_updated_at"""
        supplemental_join = """
                LEFT JOIN (
                    SELECT parent_job_id, COUNT(*) AS total,
                           SUM(CASE WHEN status IN ('queued', 'running', 'paused')
                                    THEN 1 ELSE 0 END) AS active,
                           SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
                           MAX(updated_at) AS updated_at
                    FROM research_jobs
                    WHERE job_role='supplemental'
                    GROUP BY parent_job_id
                ) AS supplemental_stats
                  ON supplemental_stats.parent_job_id=research_jobs.job_id
            """
        if include_artifacts:
            artifact_select = """
                       , COALESCE(artifact_stats.artifact_count, 0)
                           AS artifact_count,
                       COALESCE(artifact_stats.output_artifact_count, 0)
                           AS output_artifact_count,
                       COALESCE(artifact_stats.input_artifact_count, 0)
                           AS input_artifact_count,
                       COALESCE(artifact_stats.artifact_bytes, 0)
                           AS artifact_bytes,
                       COALESCE(artifact_stats.output_artifact_bytes, 0)
                           AS output_artifact_bytes,
                       COALESCE(artifact_stats.input_artifact_bytes, 0)
                           AS input_artifact_bytes"""
            artifact_join = """
                LEFT JOIN (
                    SELECT job_id,
                           COUNT(*) AS artifact_count,
                           SUM(CASE WHEN artifact_role='output' THEN 1 ELSE 0 END)
                               AS output_artifact_count,
                           SUM(CASE WHEN artifact_role='input' THEN 1 ELSE 0 END)
                               AS input_artifact_count,
                           COALESCE(SUM(size_bytes), 0) AS artifact_bytes,
                           COALESCE(SUM(CASE WHEN artifact_role='output'
                                             THEN size_bytes ELSE 0 END), 0)
                               AS output_artifact_bytes,
                           COALESCE(SUM(CASE WHEN artifact_role='input'
                                             THEN size_bytes ELSE 0 END), 0)
                               AS input_artifact_bytes
                    FROM research_job_artifacts
                    WHERE state='active'
                    GROUP BY job_id
                ) AS artifact_stats ON artifact_stats.job_id=research_jobs.job_id
            """
        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT research_jobs.job_id, research_jobs.run_id,
                       research_jobs.owner, research_jobs.workspace_id,
                       research_jobs.kind, research_jobs.status,
                       research_jobs.attempt, research_jobs.step_mode,
                       research_jobs.deployment_id,
                       research_jobs.cancel_requested_at,
                       research_jobs.created_at, research_jobs.started_at,
                       research_jobs.finished_at, research_jobs.updated_at
                       {artifact_select}
                       {supplemental_select}
                FROM research_jobs
                {artifact_join}
                {supplemental_join}
                {where}
                ORDER BY effective_updated_at DESC, research_jobs.job_id DESC
                LIMIT ?
                """,
                args,
            ).fetchall()
        has_more = len(rows) > bounded_limit
        rows = rows[:bounded_limit]
        result = [
            {
                "job_id": str(row["job_id"]),
                "run_id": str(row["run_id"]),
                "owner": str(row["owner"]),
                "workspace_id": str(row["workspace_id"]),
                "kind": str(row["kind"]),
                "status": str(row["status"]),
                "attempt": int(row["attempt"] or 1),
                "step_mode": bool(row["step_mode"]),
                "deployment_id": str(row["deployment_id"] or ""),
                "cancel_requested": row["cancel_requested_at"] is not None,
                "created_at": float(row["created_at"]),
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
                "parent_updated_at": float(row["updated_at"]),
                "updated_at": float(row["effective_updated_at"]),
                "supplemental_count": int(row["supplemental_count"] or 0),
                "supplemental_active_count": int(
                    row["supplemental_active_count"] or 0
                ),
                "supplemental_failed_count": int(
                    row["supplemental_failed_count"] or 0
                ),
                "supplemental_updated_at": row["supplemental_updated_at"],
            }
            for row in rows
        ]
        if include_artifacts:
            for item, row in zip(result, rows):
                item.update({
                    "artifact_count": int(row["artifact_count"] or 0),
                    "output_artifact_count": int(
                        row["output_artifact_count"] or 0
                    ),
                    "input_artifact_count": int(
                        row["input_artifact_count"] or 0
                    ),
                    "artifact_bytes": int(row["artifact_bytes"] or 0),
                    "output_artifact_bytes": int(
                        row["output_artifact_bytes"] or 0
                    ),
                    "input_artifact_bytes": int(
                        row["input_artifact_bytes"] or 0
                    ),
                })
        return result, has_more

    def count_global_summaries(
        self, *, object_kind: str = "", object_ref: str = "",
        object_owner_ref: str = "", object_alias: str = "",
    ) -> int:
        """Return the number of durable jobs in the shared service store."""
        clauses = ["job_role='primary'"]
        args: list[Any] = []
        _append_subject_clause(
            clauses, args, table="research_jobs",
            object_kind=object_kind, object_ref=object_ref,
            owner_ref=object_owner_ref, alias=object_alias,
        )
        with self._connection() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) AS total FROM research_jobs "
                f"WHERE {' AND '.join(clauses)}",
                args,
            ).fetchone()
        return int(row["total"] or 0) if row is not None else 0

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
        with self._connection() as conn:
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
        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM user_job_pins WHERE job_id=?",
                (str(job_id),),
            ).fetchone()
        return row is not None

    @staticmethod
    def record_from_row(row: sqlite3.Row | None) -> JobRecord | None:
        """Map one repository-owned query row to its public JobRecord."""
        if row is None:
            return None
        return JobRecord(
            job_id=str(row["job_id"]),
            run_id=str(row["run_id"]),
            owner=str(row["owner"]),
            workspace_id=str(row["workspace_id"]),
            kind=str(row["kind"]),
            status=JobStatus(row["status"]),
            job_role=str(row["job_role"] or "primary"),
            parent_job_id=str(row["parent_job_id"] or ""),
            supplemental_kind=str(row["supplemental_kind"] or ""),
            supplemental_identity=str(row["supplemental_identity"] or ""),
            source_artifact_hash=str(row["source_artifact_hash"] or ""),
            retry_of=str(row["retry_of"] or ""),
            attempt=int(row["attempt"] or 1),
            step_mode=bool(row["step_mode"]),
            retention_mode=str(row["retention_mode"]),
            deployment_id=str(row["deployment_id"] or ""),
            service_port=int(row["service_port"] or 0),
            source_revision=str(row["source_revision"] or ""),
            runner_path=str(row["runner_path"] or ""),
            job_spec=(
                _loads(row["job_spec_json"], {})
                if isinstance(_loads(row["job_spec_json"], {}), dict)
                else {}
            ),
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
            plan_notices=(
                _loads(row["plan_notices_json"], [])
                if isinstance(_loads(row["plan_notices_json"], []), list)
                else []
            ),
            result_summary=(
                _loads(row["result_summary_json"])
                if isinstance(_loads(row["result_summary_json"]), dict)
                else None
            ),
            error=(
                _loads(row["error_json"])
                if isinstance(_loads(row["error_json"]), dict)
                else None
            ),
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

    _record = record_from_row
