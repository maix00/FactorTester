"""One-read HTTP detail projection for a durable JobAttempt."""

from __future__ import annotations

import sqlite3
from typing import Any


class JobDetailQueryImplementation:
    """Join Job, pin, and immutable ResearchRun identity once."""

    def load_detail(
        self,
        job_id: str,
        *,
        owner: str,
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            try:
                row = conn.execute(
                    _DETAIL_QUERY,
                    (str(job_id), str(owner)),
                ).fetchone()
            except sqlite3.OperationalError as exc:
                if "no such table: research_runs" not in str(exc):
                    raise
                row = conn.execute(
                    _LEGACY_DETAIL_QUERY,
                    (str(job_id), str(owner)),
                ).fetchone()
        record = self._record(row)
        if record is None:
            return None
        trial_binding = _trial_binding(row)
        return {
            "job": record,
            "pinned": bool(row["detail_pinned"]),
            "trial_binding": trial_binding,
            "identity_refs": _identity_refs(row, trial_binding),
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


def _identity_refs(
    row: Any,
    trial_binding: dict[str, Any] | None,
) -> dict[str, str] | None:
    if trial_binding is None:
        return None
    value = {
        "contract_hash": str(row["run_contract_hash"] or ""),
        "methodology_hash": str(row["run_methodology_hash"] or ""),
        "trial_plan_hash": trial_binding["trial_plan_hash"],
        "run_spec_hash": str(row["run_run_spec_hash"] or ""),
    }
    return value if all(value.values()) else None


_DETAIL_COLUMNS = """
    CASE WHEN pins.job_id IS NULL THEN 0 ELSE 1 END AS detail_pinned,
    runs.decision_contract_hash AS run_contract_hash,
    runs.methodology_hash AS run_methodology_hash,
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
    runs.run_spec_hash AS run_run_spec_hash
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
           NULL AS run_contract_hash,
           NULL AS run_methodology_hash,
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
           NULL AS run_run_spec_hash
    FROM research_jobs AS jobs
    LEFT JOIN user_job_pins AS pins
      ON pins.job_id=jobs.job_id AND pins.owner=jobs.owner
    WHERE jobs.job_id=? AND jobs.owner=?
"""
