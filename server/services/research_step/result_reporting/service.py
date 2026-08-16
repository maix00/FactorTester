"""Bounded batch reads and exact legacy audit backfill."""

from __future__ import annotations
from copy import deepcopy
from typing import Any

import orjson
import settings as Settings
from server.jobs.repository.sqlite import JobRepository
from server.services.research_graph.research_cycle.job_evidence import (
    project_job_attempt_evidence,
)
from server.services.research_graph.trial_plan.adjudication_receipts import (
    backfill_action_adjudication_receipt,
    load_action_adjudication_receipt,
)
from server.services.research_graph.trial_plan.execution_checkpoint_api import (
    load_execution_checkpoint_contract,
)
from server.services.research_graph.trial_plan.execution_checkpoint_contract import (
    validate_execution_checkpoint,
)
from server.services.research_report_presentations import run_spec_presentation
from tools.data.sqlite.db import connect_sqlite

from .projection import build_result_report_projection
from .presentations import result_presentations


def load_result_report_projection(
    *, instance_id: str, branch_id: str, owner: str, action_id: str,
) -> dict[str, Any]:
    contract = load_execution_checkpoint_contract(
        instance_id=instance_id, branch_id=branch_id, owner=owner,
    )
    action = next(
        (item for item in contract["trial_plan"]["evidence_actions"]
         if item["action_id"] == action_id), None,
    )
    if action is None:
        raise KeyError("Evidence Action is not in the current TrialPlan")
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT j.*, r.kind AS run_kind, r.run_spec_json,
                   r.trial_role, r.trial_stage,
                   r.decision_contract_hash, r.methodology_hash,
                   r.trial_plan_hash AS run_trial_plan_hash
            FROM research_runs r JOIN research_jobs j
              ON j.run_id=r.run_id AND j.owner=r.owner
            WHERE r.owner=? AND r.graph_instance_id=? AND r.graph_branch_id=?
              AND r.trial_plan_hash=? AND r.evidence_action_id=?
            ORDER BY r.run_spec_hash, j.attempt, j.job_id LIMIT 32
            """,
            (owner, instance_id, branch_id, contract["trial_plan_hash"], action_id),
        ).fetchall()
        artifacts = conn.execute(
            """
            SELECT a.job_id, a.name, a.content_hash, a.content_type,
                   a.size_bytes, a.relative_path, a.retention_mode, a.state
            FROM research_job_artifacts a
            JOIN research_jobs j ON j.job_id=a.job_id
            JOIN research_runs r ON r.run_id=j.run_id AND r.owner=j.owner
            WHERE r.owner=? AND r.graph_instance_id=? AND r.graph_branch_id=?
              AND r.trial_plan_hash=? AND r.evidence_action_id=?
              AND a.state='active'
            ORDER BY a.job_id, a.name
            """,
            (owner, instance_id, branch_id, contract["trial_plan_hash"], action_id),
        ).fetchall()
        receipt = load_action_adjudication_receipt(
            conn, instance_id, branch_id, contract["trial_plan_hash"], action_id,
        )
        evidence_refs = (
            set(receipt["proposal"]["evidence_refs"]) if receipt
            else set(
                contract["checkpoint"]["current_action_output_evidence_refs"]
            )
        )
        projected = _admitted_rows(
            rows, artifacts=artifacts, evidence_refs=evidence_refs,
        )
        if not projected:
            raise ValueError("Evidence Action has no authoritative JobAttempt")
        if {row["run_spec_hash"] for row in projected} != set(
            action["run_spec_hashes"]
        ):
            raise ValueError("admitted JobAttempt RunSpec set is incomplete")
        presentations = result_presentations(
            conn,
            instance_id=instance_id,
            branch_id=branch_id,
            rows=projected,
            receipt=receipt,
        )
    report_action = deepcopy(action)
    report_action["output_evidence_refs"] = (
        list(receipt["proposal"]["evidence_refs"]) if receipt
        else (
            list(contract["checkpoint"]["current_action_output_evidence_refs"])
            if contract["checkpoint"]["current_action_id"] == action_id else []
        )
    )
    value = build_result_report_projection(
        action=report_action, plan_hash=contract["trial_plan_hash"],
        rows=projected, receipt=receipt, presentations=presentations,
    )
    return {
        **value, "instance_id": instance_id, "branch_id": branch_id,
        "node_id": contract["checkpoint"]["execution_node"],
        "audit_status": (
            "available" if receipt else "unavailable_from_registration_checkpoint"
        ),
    }


def backfill_result_audit(
    *, instance_id: str, branch_id: str, owner: str,
    audited_checkpoint: dict[str, Any], proposal: dict[str, Any],
    decision: dict[str, Any],
) -> dict[str, Any]:
    contract = load_execution_checkpoint_contract(
        instance_id=instance_id, branch_id=branch_id, owner=owner,
    )
    historical = validate_execution_checkpoint(audited_checkpoint)
    current = contract["checkpoint"]
    if historical["current_action_id"] != current["current_action_id"]:
        stage_index = historical["ordered_stage_ids"].index(
            historical["current_stage_id"]
        )
        if not current["completed_stage_mask"] & (1 << stage_index):
            raise ValueError("historical audited Action is not completed")
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute("BEGIN IMMEDIATE")
        return backfill_action_adjudication_receipt(
            conn, instance_id=instance_id, branch_id=branch_id,
            trial_plan=contract["trial_plan"], checkpoint=historical,
            proposal=proposal, decision=decision,
        )


def _admitted_rows(rows, *, artifacts, evidence_refs):
    by_job = {}
    for item in artifacts:
        by_job.setdefault(str(item["job_id"]), []).append(dict(item))
    repository = JobRepository(Settings.CACHE_DB_PATH)
    accepted = []
    for row in rows:
        job = repository.record_from_row(row)
        identity = {
            "contract_hash": str(row["decision_contract_hash"]),
            "methodology_hash": str(row["methodology_hash"]),
            "trial_plan_hash": str(row["run_trial_plan_hash"]),
            "run_spec_hash": str(row["run_spec_hash"]),
        }
        envelope = project_job_attempt_evidence(
            job, identity_refs=identity,
            trial_stage=str(row["trial_stage"]),
            active_artifacts=by_job.get(str(row["job_id"]), []),
        )
        ref = (
            "evidence:" + envelope["envelope_hash"] if envelope else ""
        )
        if ref in evidence_refs:
            accepted.append((row, ref))
    return [
        _row(row, index, evidence_ref=ref)
        for index, (row, ref) in enumerate(accepted, 1)
    ]


def _row(row, index, *, evidence_ref):
    spec = orjson.loads(row["run_spec_json"])
    presentation = run_spec_presentation(
        spec, run_spec_hash=str(row["run_spec_hash"]),
        run_id=str(row["run_id"]),
    )
    summary = orjson.loads(row["result_summary_json"] or "{}")
    return {
        "index": index, "run_id": str(row["run_id"]),
        "job_id": str(row["job_id"]), "kind": str(row["kind"]),
        "status": str(row["status"]), "trial_role": str(row["trial_role"]),
        "run_spec_hash": str(row["run_spec_hash"]),
        "run_spec_alias_zh": presentation["alias_zh"],
        "evidence_ref": evidence_ref,
        "result_summary": summary if isinstance(summary, dict) else {},
    }
