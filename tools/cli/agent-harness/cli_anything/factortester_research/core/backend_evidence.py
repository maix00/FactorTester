"""Validate server-owned evidence without reconstructing backend facts."""

from __future__ import annotations

from typing import Any

from .evidence import validate_evidence_envelope


def extract_job_attempt(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    """Return a verified JobAttempt envelope and assurance disposition."""
    evidence = payload.get("evidence")
    if not isinstance(evidence, dict):
        raise ValueError("job detail does not contain server evidence")
    assurance = evidence.get("terminal_assurance")
    if not isinstance(assurance, dict):
        raise ValueError("job is not terminal or lacks terminal assurance")
    raw_envelope = evidence.get("job_attempt")
    if not isinstance(raw_envelope, dict):
        raise ValueError("job detail lacks a server-owned JobAttempt envelope")
    envelope = validate_evidence_envelope(raw_envelope)
    facts = envelope.get("facts")
    fact_assurance = (
        facts.get("assurance") if isinstance(facts, dict) else None
    )
    if not isinstance(fact_assurance, dict):
        raise ValueError("JobAttempt evidence lacks assurance facts")
    identity = envelope["identity_refs"]
    checks = {
        "job_id": (
            str(payload.get("job_id") or ""),
            str(facts.get("job_id") or ""),
        ),
        "status": (
            str(payload.get("status") or ""),
            str(facts.get("status") or ""),
        ),
        "run_spec_hash": (
            str(assurance.get("run_spec_hash") or ""),
            str(identity.get("run_spec_hash") or ""),
        ),
        "disposition": (
            str(assurance.get("disposition") or ""),
            str(fact_assurance.get("disposition") or ""),
        ),
        "policy_hash": (
            str(assurance.get("policy_hash") or ""),
            str(fact_assurance.get("policy_hash") or ""),
        ),
        "backend_revision": (
            str(assurance.get("backend_revision") or ""),
            str(fact_assurance.get("backend_revision") or ""),
        ),
    }
    mismatch = next(
        (
            field for field, pair in checks.items()
            if not pair[0] or pair[0] != pair[1]
        ),
        "",
    )
    if mismatch:
        raise ValueError(
            f"JobAttempt evidence conflicts with terminal {mismatch}"
        )
    _require_hash_ref(
        envelope["metric_refs"],
        prefix="result-summary:sha256:",
        expected=str(assurance.get("result_summary_hash") or ""),
        optional=True,
    )
    _require_hash_ref(
        envelope["artifact_refs"],
        prefix="artifact-manifest:sha256:",
        expected=str(assurance.get("artifact_manifest_hash") or ""),
    )
    if list(fact_assurance.get("anomaly_codes") or []) != list(
        assurance.get("anomaly_codes") or []
    ):
        raise ValueError(
            "JobAttempt evidence conflicts with terminal anomaly_codes"
        )
    return envelope, checks["disposition"][0]


def _require_hash_ref(
    refs: list[str],
    *,
    prefix: str,
    expected: str,
    optional: bool = False,
) -> None:
    expected_ref = prefix + expected if expected else ""
    if optional and not expected_ref:
        if refs:
            raise ValueError(f"unexpected {prefix} reference")
        return
    if not expected_ref or expected_ref not in refs:
        raise ValueError(f"JobAttempt evidence lacks {prefix} reference")
