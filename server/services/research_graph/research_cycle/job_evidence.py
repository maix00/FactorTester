"""Deterministic EvidenceEnvelope projection for terminal JobAttempts."""

from __future__ import annotations

import re
from typing import Any

from server.jobs.models import JobRecord
from server.jobs.states import TERMINAL_STATUSES

from .evidence import validate_agent_evidence_envelope

_NET_RETURN_ARTIFACT_NAMES = {"net_returns", "net_return_series"}
_EQUITY_CURVE_ARTIFACT = "equity_curve_report"
_EQUITY_CURVE_RECEIPT = "equity_curve_receipt"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def project_job_attempt_evidence(
    job: JobRecord,
    *,
    identity_refs: dict[str, str] | None,
    trial_stage: str,
    active_artifacts: list[dict[str, Any]] | None = None,
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
    net_return_ref = _net_return_series_ref(active_artifacts or [])
    equity_curve_ref = _unique_artifact_ref(
        active_artifacts or [], name=_EQUITY_CURVE_ARTIFACT,
    )
    equity_curve_receipt_ref = _unique_artifact_ref(
        active_artifacts or [], name=_EQUITY_CURVE_RECEIPT,
    )
    artifact_refs = [
        "artifact-manifest:sha256:" + assurance.artifact_manifest_hash
    ]
    if net_return_ref is not None:
        artifact_refs.append(net_return_ref)
    artifact_refs.extend(
        ref for ref in (equity_curve_ref, equity_curve_receipt_ref)
        if ref is not None
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
            "net_return_series_available": net_return_ref is not None,
            "equity_curve_report_available": equity_curve_ref is not None,
            "equity_curve_source_retained": net_return_ref is not None,
            **(
                {"net_return_series_ref": net_return_ref}
                if net_return_ref is not None else {}
            ),
            "assurance": {
                "policy_hash": assurance.policy_hash,
                "backend_revision": assurance.backend_revision,
                "disposition": assurance.disposition,
                "anomaly_codes": list(assurance.anomaly_codes),
            },
        },
        "metric_refs": metric_refs,
        "artifact_refs": artifact_refs,
        "hypotheses_tested": 0,
        "stop_condition": None,
        "limitations": [
            "The backend does not emit a canonical hypotheses-tested count."
        ],
        "conflicts": [],
    }
    return validate_agent_evidence_envelope(envelope)


def _net_return_series_ref(
    artifacts: list[dict[str, Any]],
) -> str | None:
    if not isinstance(artifacts, list):
        raise ValueError("active_artifacts must be an array")
    matches: list[str] = []
    for item in artifacts:
        if not isinstance(item, dict):
            raise ValueError("active artifact metadata must be an object")
        name = str(item.get("name") or "")
        if name not in _NET_RETURN_ARTIFACT_NAMES:
            continue
        content_hash = str(item.get("content_hash") or "")
        if _SHA256.fullmatch(content_hash) is None:
            raise ValueError("net return artifact requires a SHA-256 hash")
        matches.append(
            f"artifact:{name}:sha256:{content_hash}"
        )
    if len(matches) > 1:
        raise ValueError("JobAttempt has ambiguous net return artifacts")
    return matches[0] if matches else None


def _unique_artifact_ref(
    artifacts: list[dict[str, Any]], *, name: str,
) -> str | None:
    if not isinstance(artifacts, list):
        raise ValueError("active_artifacts must be an array")
    matches = []
    for item in artifacts:
        if not isinstance(item, dict):
            raise ValueError("active artifact metadata must be an object")
        if str(item.get("name") or "") != name:
            continue
        content_hash = str(item.get("content_hash") or "")
        if _SHA256.fullmatch(content_hash) is None:
            raise ValueError(f"{name} artifact requires a SHA-256 hash")
        matches.append(f"artifact:{name}:sha256:{content_hash}")
    if len(matches) > 1:
        raise ValueError(f"JobAttempt has ambiguous {name} artifacts")
    return matches[0] if matches else None
