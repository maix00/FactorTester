"""Artifact metadata, retention, and storage policy Implementation."""

from __future__ import annotations

import time
from typing import Any

from ..states import JobStatus, TERMINAL_STATUSES


class JobArtifactImplementation:
    """Own artifact lifecycle and quota queries behind JobRepository."""

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
        artifact_role: str = "output",
        artifact_kind: str = "",
        file_name: str = "",
        logical_path: str = "",
        title_zh: str = "",
    ) -> dict[str, Any]:
        now = time.time()
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            job = conn.execute(
                "SELECT status FROM research_jobs WHERE job_id=?",
                (str(job_id),),
            ).fetchone()
            if job is None:
                raise KeyError("research job not found")
            if JobStatus(job["status"]) in TERMINAL_STATUSES:
                raise ValueError("terminal job artifacts are immutable")
            stored = conn.execute(
                """
                INSERT INTO research_job_artifacts (
                    job_id, name, artifact_role, artifact_kind, file_name,
                    logical_path, title_zh, retention_mode, state, content_type,
                    relative_path, content_hash, size_bytes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?)
                ON CONFLICT(job_id, name) DO UPDATE SET
                    artifact_role=excluded.artifact_role,
                    artifact_kind=excluded.artifact_kind,
                    file_name=excluded.file_name,
                    logical_path=excluded.logical_path,
                    title_zh=excluded.title_zh,
                    retention_mode=excluded.retention_mode,
                    state='active', content_type=excluded.content_type,
                    relative_path=excluded.relative_path,
                    content_hash=excluded.content_hash,
                    size_bytes=excluded.size_bytes, created_at=excluded.created_at,
                    deleted_at=NULL
                RETURNING *
                """,
                (
                    str(job_id),
                    str(name),
                    str(artifact_role),
                    str(artifact_kind),
                    str(file_name),
                    str(logical_path),
                    str(title_zh),
                    str(retention_mode),
                    str(content_type),
                    str(relative_path),
                    str(content_hash),
                    max(0, int(size_bytes)),
                    now,
                ),
            ).fetchone()
        if stored is None:
            raise RuntimeError("artifact write returned no record")
        return dict(stored)

    def record_derived_artifact(
        self,
        *,
        job_id: str,
        name: str,
        relative_path: str,
        content_type: str,
        content_hash: str,
        size_bytes: int,
        retention_mode: str = "retained",
        artifact_role: str = "output",
        artifact_kind: str = "",
        file_name: str = "",
        logical_path: str = "",
        title_zh: str = "",
    ) -> dict[str, Any]:
        """Record a user-requested report generated after terminalization.

        Execution artifacts remain immutable once a Job is terminal.  Derived
        reports are separately named and may be regenerated, so they use the
        same metadata table with an explicit terminal-safe path.
        """
        now = time.time()
        with self._connection() as conn:
            row = conn.execute(
                "SELECT job_id FROM research_jobs WHERE job_id=?",
                (str(job_id),),
            ).fetchone()
            if row is None:
                raise KeyError("research job not found")
            stored = conn.execute(
                """
                INSERT INTO research_job_artifacts (
                    job_id, name, artifact_role, artifact_kind, file_name,
                    logical_path, title_zh, retention_mode, state, content_type,
                    relative_path, content_hash, size_bytes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?)
                ON CONFLICT(job_id, name) DO UPDATE SET
                    artifact_role=excluded.artifact_role,
                    artifact_kind=excluded.artifact_kind,
                    file_name=excluded.file_name,
                    logical_path=excluded.logical_path,
                    title_zh=excluded.title_zh,
                    retention_mode=excluded.retention_mode,
                    state='active', content_type=excluded.content_type,
                    relative_path=excluded.relative_path,
                    content_hash=excluded.content_hash,
                    size_bytes=excluded.size_bytes, created_at=excluded.created_at,
                    deleted_at=NULL
                RETURNING *
                """,
                (
                    str(job_id), str(name), str(artifact_role),
                    str(artifact_kind), str(file_name), str(logical_path),
                    str(title_zh),
                    str(retention_mode), str(content_type), str(relative_path),
                    str(content_hash), max(0, int(size_bytes)), now,
                ),
            ).fetchone()
        if stored is None:
            raise RuntimeError("derived artifact write returned no record")
        return dict(stored)

    def load_artifact(
        self,
        *,
        job_id: str,
        name: str,
        owner: str,
    ) -> dict[str, Any] | None:
        with self._connection() as conn:
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
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM research_job_artifacts
                WHERE job_id=? AND name=?
                """,
                (str(job_id), str(name)),
            ).fetchone()
        if row is None:
            raise KeyError("research job artifact not found")
        return dict(row)

    def list_artifacts(
        self,
        *,
        job_id: str,
        owner: str,
    ) -> list[dict[str, Any]]:
        with self._connection() as conn:
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

    def mark_artifacts_deleted(
        self,
        *,
        job_id: str,
        owner: str,
    ) -> list[dict[str, Any]]:
        artifacts = self.list_artifacts(job_id=job_id, owner=owner)
        now = time.time()
        with self._connection() as conn:
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
        self,
        *,
        owner: str,
        workspace_id: str = "",
    ) -> list[dict[str, Any]]:
        clauses = ["jobs.owner=?", "artifacts.state != 'deleted'"]
        args: list[Any] = [str(owner)]
        if workspace_id:
            clauses.append("jobs.workspace_id=?")
            args.append(str(workspace_id))
        now = time.time()
        with self._connection() as conn:
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

    def delete_terminal_history(
        self,
        *,
        owner: str,
        workspace_id: str,
    ) -> tuple[list[str], list[dict[str, Any]]]:
        if not workspace_id:
            raise ValueError("workspace_id is required")
        terminal = tuple(status.value for status in TERMINAL_STATUSES)
        placeholders = ",".join("?" for _ in terminal)
        args = [str(owner), str(workspace_id), *terminal]
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            jobs = conn.execute(
                f"""
                SELECT job_id FROM research_jobs
                WHERE owner=? AND workspace_id=?
                  AND status IN ({placeholders})
                ORDER BY updated_at, job_id
                """,
                args,
            ).fetchall()
            job_ids = [str(row["job_id"]) for row in jobs]
            if not job_ids:
                return [], []
            job_placeholders = ",".join("?" for _ in job_ids)
            artifacts = conn.execute(
                f"""
                SELECT * FROM research_job_artifacts
                WHERE job_id IN ({job_placeholders})
                ORDER BY job_id, created_at, name
                """,
                job_ids,
            ).fetchall()
            conn.execute(
                f"""
                DELETE FROM research_jobs
                WHERE owner=? AND workspace_id=?
                  AND status IN ({placeholders})
                """,
                args,
            )
        return job_ids, [dict(row) for row in artifacts]

    def storage_usage(self, *, owner: str) -> int:
        with self._connection() as conn:
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

    def storage_breakdown(self, *, owner: str) -> dict[str, int]:
        """Return active retained bytes split into submitted inputs and outputs."""
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS artifact_count,
                    COALESCE(SUM(size_bytes), 0) AS artifact_bytes,
                    SUM(CASE WHEN artifacts.artifact_role='output'
                             THEN 1 ELSE 0 END) AS output_artifact_count,
                    COALESCE(SUM(CASE WHEN artifacts.artifact_role='output'
                                      THEN artifacts.size_bytes ELSE 0 END), 0)
                        AS output_artifact_bytes,
                    SUM(CASE WHEN artifacts.artifact_role='input'
                             THEN 1 ELSE 0 END) AS input_artifact_count,
                    COALESCE(SUM(CASE WHEN artifacts.artifact_role='input'
                                      THEN artifacts.size_bytes ELSE 0 END), 0)
                        AS input_artifact_bytes
                FROM research_job_artifacts AS artifacts
                JOIN research_jobs AS jobs ON jobs.job_id=artifacts.job_id
                WHERE jobs.owner=? AND artifacts.state='active'
                """,
                (str(owner),),
            ).fetchone()
        return {
            "artifact_count": int(row["artifact_count"] or 0),
            "artifact_bytes": int(row["artifact_bytes"] or 0),
            "output_artifact_count": int(row["output_artifact_count"] or 0),
            "output_artifact_bytes": int(
                row["output_artifact_bytes"] or 0
            ),
            "input_artifact_count": int(row["input_artifact_count"] or 0),
            "input_artifact_bytes": int(row["input_artifact_bytes"] or 0),
        }

    def storage_quota(self, *, owner: str, default_bytes: int) -> int:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT quota_bytes FROM user_storage_policies WHERE owner=?",
                (str(owner),),
            ).fetchone()
        return (
            int(row["quota_bytes"])
            if row is not None
            else max(0, int(default_bytes))
        )

    def set_storage_quota(self, *, owner: str, quota_bytes: int) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO user_storage_policies(owner, quota_bytes, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(owner) DO UPDATE SET
                    quota_bytes=excluded.quota_bytes, updated_at=excluded.updated_at
                """,
                (str(owner), max(0, int(quota_bytes)), time.time()),
            )
