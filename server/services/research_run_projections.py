"""Read projections for immutable ResearchRun and Job evidence bindings."""

from __future__ import annotations

import sqlite3
from typing import Any

import orjson


def project_run(row: sqlite3.Row) -> dict[str, Any]:
    value = {
        "run_id": str(row["run_id"]),
        "owner": str(row["owner"]),
        "workspace_id": str(row["workspace_id"]),
        "configuration_id": str(row["configuration_id"]),
        "configuration_revision": int(row["configuration_revision"]),
        "kind": str(row["kind"]),
        "run_spec_version": int(row["run_spec_version"]),
        "run_spec_hash": str(row["run_spec_hash"]),
        "run_spec": orjson.loads(row["run_spec_json"]),
        "report_binding": (
            orjson.loads(row["report_binding_json"])
            if str(row["report_binding_json"] or "{}") != "{}"
            else None
        ),
        "sample_identity_hash": str(row["sample_identity_hash"]),
        "sample_start": str(row["sample_start"]),
        "sample_end": str(row["sample_end"]),
        "sample_universe_hash": str(row["sample_universe_hash"]),
        "sample_design_context_hash": str(row["sample_design_context_hash"]),
        "sample_identity_assurance": str(row["sample_identity_assurance"]),
        "sample_use": (
            orjson.loads(row["sample_use_json"])
            if str(row["sample_use_json"] or "{}") != "{}"
            else None
        ),
        "created_at": float(row["created_at"]),
    }
    # Keep the historic binding shape only when loading a legacy Run. New Runs
    # have no TrialPlan identity and should not manufacture empty sentinels.
    trial_plan_hash = str(row["trial_plan_hash"] or "")
    if trial_plan_hash:
        value.update({
            "trial_plan_id": str(row["trial_plan_id"]),
            "trial_plan_hash": trial_plan_hash,
            "trial_plan_schema_version": int(row["trial_plan_schema_version"]),
            "trial_plan_version": int(row["trial_plan_version"]),
            "trial_role": str(row["trial_role"]),
            "trial_stage": str(row["trial_stage"]),
            "comparison_id": str(row["comparison_id"]),
            "sample_ref": str(row["sample_ref"]),
            "sample_hash": str(row["sample_hash"]),
        })
    return value


def project_job_evidence(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    owner: str,
) -> dict[str, Any] | None:
    try:
        row = conn.execute(_JOB_EVIDENCE_QUERY, (job_id, owner, owner)).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table: research_jobs" not in str(exc):
            raise
        return None
    if row is None or not str(row["run_spec_hash"] or ""):
        return None
    trial_binding = None
    if str(row["trial_plan_hash"] or ""):
        trial_binding = {
            "trial_plan_id": str(row["trial_plan_id"]),
            "trial_plan_hash": str(row["trial_plan_hash"]),
            "trial_plan_version": int(row["trial_plan_version"]),
            "trial_role": str(row["trial_role"]),
            "trial_stage": str(row["trial_stage"]),
            "comparison_id": str(row["comparison_id"]),
            "sample_ref": str(row["sample_ref"]),
            "sample_hash": str(row["sample_hash"]),
            "sample_identity_hash": str(row["sample_identity_hash"]),
            "sample_identity_assurance": str(row["sample_identity_assurance"]),
        }
    identity_refs = {"run_spec_hash": str(row["run_spec_hash"])}
    if str(row["trial_plan_hash"] or ""):
        identity_refs["trial_plan_hash"] = str(row["trial_plan_hash"])
    if str(row["sample_use_hash"] or ""):
        identity_refs["sample_use_hash"] = str(row["sample_use_hash"])
    return {
        "trial_binding": trial_binding,
        "identity_refs": identity_refs,
    }


_JOB_EVIDENCE_QUERY = """
    SELECT runs.trial_plan_id, runs.trial_plan_hash,
           runs.trial_plan_version, runs.trial_role, runs.trial_stage,
           runs.comparison_id, runs.sample_ref, runs.sample_hash,
           runs.sample_identity_hash, runs.sample_identity_assurance,
           runs.run_spec_hash, runs.sample_use_hash
    FROM research_jobs AS jobs
    JOIN research_runs AS runs ON runs.run_id=jobs.run_id
    WHERE jobs.job_id=? AND jobs.owner=? AND runs.owner=?
"""
