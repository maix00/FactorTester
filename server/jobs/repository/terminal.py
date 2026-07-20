"""Terminal JobAttempt transaction helpers."""

from __future__ import annotations

import sqlite3
from typing import Any

from ..assurance import BackendAssuranceValidator, TerminalAssuranceSummary
from server.services.maintenance_cases.backend_anomalies import (
    backend_anomaly_case_spec,
)
from server.services.maintenance_cases.store import open_case_in_connection


def evaluate_terminal_assurance(
    conn: sqlite3.Connection,
    *,
    row: sqlite3.Row,
    terminal_status: str,
    result_summary: dict[str, Any] | None,
    error: dict[str, Any] | None,
    worker_exitcode: int | None,
    job_spec: dict[str, Any],
    execution_plan: dict[str, Any] | None,
    validator: BackendAssuranceValidator,
) -> TerminalAssuranceSummary:
    artifacts = conn.execute(
        """
        SELECT name, content_hash, size_bytes, state
        FROM research_job_artifacts
        WHERE job_id=?
        ORDER BY name
        """,
        (str(row["job_id"]),),
    ).fetchall()
    manifest = [
        {
            "name": str(artifact["name"]),
            "content_hash": str(artifact["content_hash"]),
            "size_bytes": int(artifact["size_bytes"]),
            "state": str(artifact["state"]),
        }
        for artifact in artifacts
    ]
    summary = validator.evaluate(
        terminal_status=terminal_status,
        backend_revision=str(row["source_revision"] or ""),
        run_spec_hash=str(row["run_spec_hash"] or ""),
        job_spec=job_spec,
        job_spec_hash=str(row["job_spec_hash"]),
        execution_plan=execution_plan,
        execution_plan_hash=str(row["execution_plan_hash"] or ""),
        result_summary=result_summary,
        error=error,
        worker_exitcode=worker_exitcode,
        artifact_manifest=manifest,
    )
    if summary.disposition == "maintenance_required":
        open_case_in_connection(
            conn,
            **backend_anomaly_case_spec(
                owner_user_id=str(row["owner"]),
                job_id=str(row["job_id"]),
                policy_hash=summary.policy_hash,
                anomaly_codes=list(summary.anomaly_codes),
            ),
        )
    return summary
