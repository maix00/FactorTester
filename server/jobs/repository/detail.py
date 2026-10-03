"""One-read HTTP detail projection for a durable JobAttempt."""

from __future__ import annotations

import sqlite3
from typing import Any

import orjson


class JobDetailQueryImplementation:
    """Join Job, pin, and immutable ResearchRun identity once."""

    def load_detail(
        self,
        job_id: str,
        *,
        owner: str | None,
    ) -> dict[str, Any] | None:
        owner_clause = "jobs.owner=?" if owner is not None else "1=1"
        args = (str(job_id), str(owner)) if owner is not None else (str(job_id),)
        with self._connection() as conn:
            try:
                row = conn.execute(
                    _DETAIL_QUERY.replace("jobs.owner=?", owner_clause),
                    args,
                ).fetchone()
            except sqlite3.OperationalError as exc:
                if "no such table: research_runs" not in str(exc):
                    raise
                row = conn.execute(
                    _LEGACY_DETAIL_QUERY.replace("jobs.owner=?", owner_clause),
                    args,
                ).fetchone()
        record = self._record(row)
        if record is None:
            return None
        trial_binding = _trial_binding(row)
        try:
            active_artifacts = orjson.loads(
                row["detail_artifacts_json"] or "[]"
            )
        except (orjson.JSONDecodeError, TypeError, ValueError):
            active_artifacts = []
        if not isinstance(active_artifacts, list):
            active_artifacts = []
        return {
            "job": record,
            "pinned": bool(row["detail_pinned"]),
            "trial_binding": trial_binding,
            "report_binding": _report_binding(row),
            "identity_refs": _identity_refs(row, trial_binding),
            "active_artifacts": active_artifacts,
        }


def _trial_binding(row: Any) -> dict[str, Any] | None:
    if not str(row["run_trial_plan_hash"] or ""):
        return None
    return {
        "trial_plan_id": str(row["run_trial_plan_id"] or ""),
        "trial_plan_hash": str(row["run_trial_plan_hash"]),
        "trial_plan_version": int(row["run_trial_plan_version"] or 0),
        "trial_role": str(row["run_trial_role"] or ""),
        "trial_stage": str(row["run_trial_stage"] or ""),
        "comparison_id": str(row["run_comparison_id"] or ""),
        "sample_ref": str(row["run_sample_ref"] or ""),
        "sample_hash": str(row["run_sample_hash"] or ""),
        "sample_identity_hash": str(
            row["run_sample_identity_hash"] or ""
        ),
        "sample_identity_assurance": str(
            row["run_sample_identity_assurance"] or ""
        ),
    }


def _report_binding(row: Any) -> dict[str, Any] | None:
    try:
        value = orjson.loads(str(row["run_report_binding_json"] or "{}"))
    except (orjson.JSONDecodeError, TypeError, ValueError):
        return None
    return value if isinstance(value, dict) and value else None


def _identity_refs(
    row: Any,
    trial_binding: dict[str, Any] | None,
) -> dict[str, str] | None:
    if trial_binding is None:
        return None
    value = {
        "trial_plan_hash": trial_binding["trial_plan_hash"],
        "run_spec_hash": str(row["run_run_spec_hash"] or ""),
    }
    return value if all(value.values()) else None


_DETAIL_COLUMNS = """
    CASE WHEN pins.job_id IS NULL THEN 0 ELSE 1 END AS detail_pinned,
    runs.trial_plan_id AS run_trial_plan_id,
    runs.trial_plan_hash AS run_trial_plan_hash,
    runs.trial_plan_version AS run_trial_plan_version,
    runs.trial_role AS run_trial_role,
    runs.trial_stage AS run_trial_stage,
    runs.comparison_id AS run_comparison_id,
    runs.sample_ref AS run_sample_ref,
    runs.sample_hash AS run_sample_hash,
    runs.sample_identity_hash AS run_sample_identity_hash,
    runs.sample_identity_assurance AS run_sample_identity_assurance,
    runs.report_binding_json AS run_report_binding_json,
    runs.run_spec_hash AS run_run_spec_hash,
    COALESCE((
        SELECT json_group_array(json_object(
            'name', evidence_artifacts.name,
            'content_hash', evidence_artifacts.content_hash,
            'content_type', evidence_artifacts.content_type,
            'size_bytes', evidence_artifacts.size_bytes
        ))
        FROM (
            SELECT name, content_hash, content_type, size_bytes
            FROM research_job_artifacts
            WHERE job_id=jobs.job_id AND state='active'
              AND name IN (
                'net_returns', 'net_return_series',
                'equity_curve_report', 'equity_curve_receipt'
              )
            ORDER BY name
        ) AS evidence_artifacts
    ), '[]') AS detail_artifacts_json
"""

_DETAIL_QUERY = f"""
    SELECT jobs.*, {_DETAIL_COLUMNS}
    FROM research_jobs AS jobs
    LEFT JOIN user_job_pins AS pins
      ON pins.job_id=jobs.job_id AND pins.owner=jobs.owner
    LEFT JOIN research_runs AS runs
      ON runs.run_id=jobs.run_id AND runs.owner=jobs.owner
    WHERE jobs.job_id=? AND jobs.owner=?
"""

_LEGACY_DETAIL_QUERY = """
    SELECT jobs.*,
           CASE WHEN pins.job_id IS NULL
                THEN 0 ELSE 1 END AS detail_pinned,
           NULL AS run_trial_plan_id,
           NULL AS run_trial_plan_hash,
           NULL AS run_trial_plan_version,
           NULL AS run_trial_role,
           NULL AS run_trial_stage,
           NULL AS run_comparison_id,
           NULL AS run_sample_ref,
           NULL AS run_sample_hash,
           NULL AS run_sample_identity_hash,
           NULL AS run_sample_identity_assurance,
           NULL AS run_report_binding_json,
           NULL AS run_run_spec_hash,
           '[]' AS detail_artifacts_json
    FROM research_jobs AS jobs
    LEFT JOIN user_job_pins AS pins
      ON pins.job_id=jobs.job_id AND pins.owner=jobs.owner
    WHERE jobs.job_id=? AND jobs.owner=?
"""
