"""Read projections for immutable ResearchRun and Job evidence bindings."""

from __future__ import annotations

import sqlite3
from typing import Any

import orjson


def project_run(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "run_id": str(row["run_id"]),
        "owner": str(row["owner"]),
        "workspace_id": str(row["workspace_id"]),
        "configuration_id": str(row["configuration_id"]),
        "configuration_revision": int(row["configuration_revision"]),
        "kind": str(row["kind"]),
        "run_spec_version": int(row["run_spec_version"]),
        "run_spec_hash": str(row["run_spec_hash"]),
        "run_spec": orjson.loads(row["run_spec_json"]),
        "decision_contract_hash": str(row["decision_contract_hash"]),
        "methodology_hash": str(row["methodology_hash"]),
        "trial_plan_id": str(row["trial_plan_id"]),
        "trial_plan_hash": str(row["trial_plan_hash"]),
        "trial_plan_schema_version": int(row["trial_plan_schema_version"]),
        "trial_plan_version": int(row["trial_plan_version"]),
        "trial_role": str(row["trial_role"]),
        "trial_stage": str(row["trial_stage"]),
        "trial_stage_id": str(row["trial_stage_id"]),
        "comparison_id": str(row["comparison_id"]),
        "graph_instance_id": str(row["graph_instance_id"]),
        "graph_branch_id": str(row["graph_branch_id"]),
        "sample_ref": str(row["sample_ref"]),
        "sample_hash": str(row["sample_hash"]),
        "evidence_action_id": str(row["evidence_action_id"]),
        "evidence_action_binding_hash": str(
            row["evidence_action_binding_hash"]
        ),
        "evidence_action_binding": (
            orjson.loads(row["evidence_action_binding_json"])
            if str(row["evidence_action_id"])
            else None
        ),
        "sample_identity_hash": str(row["sample_identity_hash"]),
        "sample_start": str(row["sample_start"]),
        "sample_end": str(row["sample_end"]),
        "sample_universe_hash": str(row["sample_universe_hash"]),
        "sample_design_context_hash": str(
            row["sample_design_context_hash"]
        ),
        "sample_identity_assurance": str(row["sample_identity_assurance"]),
        "created_at": float(row["created_at"]),
    }


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
    if row is None or not str(row["trial_plan_hash"]):
        return None
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
    if str(row["evidence_action_id"]):
        trial_binding.update({
            "trial_plan_schema_version": int(row["trial_plan_schema_version"]),
            "trial_stage_id": str(row["trial_stage_id"]),
            "evidence_action_id": str(row["evidence_action_id"]),
            "evidence_action_binding_hash": str(
                row["evidence_action_binding_hash"]
            ),
            "evidence_action_binding": orjson.loads(
                row["evidence_action_binding_json"]
            ),
        })
    identity = {
        "contract_hash": str(row["decision_contract_hash"]),
        "methodology_hash": str(row["methodology_hash"]),
        "trial_plan_hash": str(row["trial_plan_hash"]),
        "run_spec_hash": str(row["run_spec_hash"]),
    }
    return {
        "trial_binding": trial_binding,
        "identity_refs": identity if all(identity.values()) else None,
    }


_JOB_EVIDENCE_QUERY = """
    SELECT runs.trial_plan_id, runs.trial_plan_hash,
           runs.trial_plan_schema_version, runs.trial_plan_version,
           runs.trial_role, runs.trial_stage, runs.trial_stage_id,
           runs.comparison_id, runs.sample_ref, runs.sample_hash,
           runs.sample_identity_hash, runs.sample_identity_assurance,
           runs.decision_contract_hash, runs.methodology_hash,
           runs.run_spec_hash, runs.evidence_action_id,
           runs.evidence_action_binding_hash, runs.evidence_action_binding_json
    FROM research_jobs AS jobs
    JOIN research_runs AS runs ON runs.run_id=jobs.run_id
    WHERE jobs.job_id=? AND jobs.owner=? AND runs.owner=?
"""
