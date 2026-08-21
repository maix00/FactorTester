"""Persistent custom-analysis tabs attached to a primary Job."""

from __future__ import annotations

import time
from typing import Any


class JobCustomAnalysisImplementation:
    def create_custom_analysis(
        self,
        *,
        parent_job_id: str,
        owner: str,
        title: str,
        source: str,
        tab_id: str,
    ) -> dict[str, Any]:
        now = time.time()
        normalized_title = str(title).strip()[:120]
        normalized_source = str(source)
        if not tab_id or not normalized_title:
            raise ValueError("custom analysis tab_id and title are required")
        with self._connection() as conn:
            parent = conn.execute(
                """
                SELECT job_id FROM research_jobs
                WHERE job_id=? AND owner=? AND job_role='primary'
                """,
                (str(parent_job_id), str(owner)),
            ).fetchone()
            if parent is None:
                raise KeyError("research job not found")
            conn.execute(
                """
                INSERT INTO research_job_custom_analyses (
                    parent_job_id, tab_id, title, draft_source,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(parent_job_id), str(tab_id), normalized_title,
                    normalized_source, now, now,
                ),
            )
        return self.require_custom_analysis(
            parent_job_id=parent_job_id, owner=owner, tab_id=tab_id,
        )

    def list_custom_analyses(
        self, *, parent_job_id: str, owner: str,
    ) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT analyses.*
                FROM research_job_custom_analyses AS analyses
                JOIN research_jobs AS jobs
                  ON jobs.job_id=analyses.parent_job_id
                WHERE analyses.parent_job_id=? AND jobs.owner=?
                  AND jobs.job_role='primary'
                ORDER BY analyses.created_at, analyses.tab_id
                """,
                (str(parent_job_id), str(owner)),
            ).fetchall()
        return [self._custom_analysis_value(row) for row in rows]

    def load_custom_analysis(
        self, *, parent_job_id: str, owner: str, tab_id: str,
    ) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT analyses.*
                FROM research_job_custom_analyses AS analyses
                JOIN research_jobs AS jobs
                  ON jobs.job_id=analyses.parent_job_id
                WHERE analyses.parent_job_id=? AND analyses.tab_id=?
                  AND jobs.owner=? AND jobs.job_role='primary'
                """,
                (str(parent_job_id), str(tab_id), str(owner)),
            ).fetchone()
        return self._custom_analysis_value(row) if row is not None else None

    def require_custom_analysis(
        self, *, parent_job_id: str, owner: str, tab_id: str,
    ) -> dict[str, Any]:
        value = self.load_custom_analysis(
            parent_job_id=parent_job_id, owner=owner, tab_id=tab_id,
        )
        if value is None:
            raise KeyError("custom analysis tab not found")
        return value

    def update_custom_analysis(
        self,
        *,
        parent_job_id: str,
        owner: str,
        tab_id: str,
        title: str,
        source: str,
    ) -> dict[str, Any]:
        normalized_title = str(title).strip()[:120]
        if not normalized_title:
            raise ValueError("custom analysis title is required")
        with self._connection() as conn:
            cursor = conn.execute(
                """
                UPDATE research_job_custom_analyses
                SET title=?, draft_source=?, updated_at=?
                WHERE parent_job_id=? AND tab_id=?
                  AND parent_job_id IN (
                    SELECT job_id FROM research_jobs
                    WHERE owner=? AND job_role='primary'
                  )
                """,
                (
                    normalized_title, str(source), time.time(),
                    str(parent_job_id), str(tab_id), str(owner),
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError("custom analysis tab not found")
        return self.require_custom_analysis(
            parent_job_id=parent_job_id, owner=owner, tab_id=tab_id,
        )

    def delete_custom_analysis(
        self, *, parent_job_id: str, owner: str, tab_id: str,
    ) -> dict[str, Any]:
        current = self.require_custom_analysis(
            parent_job_id=parent_job_id, owner=owner, tab_id=tab_id,
        )
        with self._connection() as conn:
            conn.execute(
                """
                DELETE FROM research_job_custom_analyses
                WHERE parent_job_id=? AND tab_id=?
                  AND parent_job_id IN (
                    SELECT job_id FROM research_jobs
                    WHERE owner=? AND job_role='primary'
                  )
                """,
                (str(parent_job_id), str(tab_id), str(owner)),
            )
        return current

    @staticmethod
    def _custom_analysis_value(row) -> dict[str, Any]:
        return {
            "parent_job_id": str(row["parent_job_id"]),
            "tab_id": str(row["tab_id"]),
            "title": str(row["title"]),
            "source": str(row["draft_source"]),
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
        }
