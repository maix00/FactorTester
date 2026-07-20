"""Deterministic EvidenceEnvelope projection for terminal JobAttempts."""

from __future__ import annotations

from typing import Any

from server.jobs.models import JobRecord
from server.jobs.states import TERMINAL_STATUSES

from .evidence import validate_agent_evidence_envelope


def project_job_attempt_evidence(
    job: JobRecord,
    *,
    identity_refs: dict[str, str] | None,
    trial_stage: str,
) -> dict[str, Any] | None:
    """Project bounded facts only when server-owned terminal identity exists."""
    assurance = job.terminal_assurance
    if (
        job.status not in TERMINAL_STATUSES
        or assurance is None
        or identity_refs is None
    ):
        return None
    if assurance.run_spec_hash != identity_refs.get("run_spec_hash"):
        return None
    metric_refs = (
        [f"result-summary:sha256:{assurance.result_summary_hash}"]
        if assurance.result_summary_hash
        else []
    )
    envelope = {
        "schema_version": 2,
        "envelope_id": f"job-attempt:{job.job_id}",
        "evidence_kind": "job_attempt",
        "source_refs": [
            f"research-job:{job.job_id}",
            f"research-run:{job.run_id}",
        ],
        "identity_refs": dict(identity_refs),
        "facts": {
            "job_id": job.job_id,
            "run_id": job.run_id,
            "kind": job.kind,
            "status": job.status.value,
            "attempt": job.attempt,
            "trial_stage": trial_stage,
            "assurance": {
                "policy_hash": assurance.policy_hash,
                "backend_revision": assurance.backend_revision,
                "disposition": assurance.disposition,
                "anomaly_codes": list(assurance.anomaly_codes),
            },
        },
        "metric_refs": metric_refs,
        "artifact_refs": [
            "artifact-manifest:sha256:"
            + assurance.artifact_manifest_hash
        ],
        "hypotheses_tested": 0,
        "stop_condition": None,
        "limitations": [
            "The backend does not emit a canonical hypotheses-tested count."
        ],
        "conflicts": [],
    }
    return validate_agent_evidence_envelope(envelope)
