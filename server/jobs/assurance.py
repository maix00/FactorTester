"""Deterministic terminal assurance for immutable JobAttempt facts."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any

import orjson


_CHECK_TERMINAL_STATE = 1
_CHECK_JOB_SPEC_HASH = 2
_CHECK_EXECUTION_PLAN_HASH = 4
_CHECK_RUN_SPEC_HASH = 8
_CHECK_RESULT_STATE = 16
_CHECK_ARTIFACT_HASHES = 32
_CHECK_BACKEND_REVISION = 64

BACKEND_ASSURANCE_POLICY = {
    "policy_id": "backend-assurance@1",
    "checks": [
        "terminal_state",
        "job_spec_hash",
        "execution_plan_hash",
        "run_spec_hash",
        "result_state_coherence",
        "artifact_manifest_hashes",
        "backend_revision",
    ],
}


def canonical_hash(value: Any) -> str:
    raw = orjson.dumps(
        value,
        option=orjson.OPT_SORT_KEYS | orjson.OPT_SERIALIZE_NUMPY,
    )
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class TerminalAssuranceSummary:
    policy_hash: str
    backend_revision: str
    run_spec_hash: str
    checks_bitmap: int
    anomaly_codes: tuple[str, ...]
    result_summary_hash: str
    artifact_manifest_hash: str
    disposition: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_hash": self.policy_hash,
            "backend_revision": self.backend_revision,
            "run_spec_hash": self.run_spec_hash,
            "checks_bitmap": self.checks_bitmap,
            "anomaly_codes": list(self.anomaly_codes),
            "result_summary_hash": self.result_summary_hash,
            "artifact_manifest_hash": self.artifact_manifest_hash,
            "disposition": self.disposition,
        }

    @classmethod
    def from_dict(
        cls,
        value: dict[str, Any] | None,
    ) -> "TerminalAssuranceSummary | None":
        if value is None:
            return None
        return cls(
            policy_hash=str(value["policy_hash"]),
            backend_revision=str(value["backend_revision"]),
            run_spec_hash=str(value["run_spec_hash"]),
            checks_bitmap=int(value["checks_bitmap"]),
            anomaly_codes=tuple(str(code) for code in value["anomaly_codes"]),
            result_summary_hash=str(value["result_summary_hash"]),
            artifact_manifest_hash=str(value["artifact_manifest_hash"]),
            disposition=str(value["disposition"]),
        )


class BackendAssuranceValidator:
    """Evaluate canonical terminal facts without rerunning computation."""

    def __init__(self, policy: dict[str, Any] | None = None) -> None:
        self.policy = dict(policy or BACKEND_ASSURANCE_POLICY)
        self.policy_hash = canonical_hash(self.policy)

    def evaluate(
        self,
        *,
        terminal_status: str,
        backend_revision: str,
        run_spec_hash: str,
        job_spec: dict[str, Any],
        job_spec_hash: str,
        execution_plan: dict[str, Any] | None,
        execution_plan_hash: str,
        result_summary: dict[str, Any] | None,
        error: dict[str, Any] | None,
        worker_exitcode: int | None,
        artifact_manifest: list[dict[str, Any]],
    ) -> TerminalAssuranceSummary:
        anomalies: list[str] = []
        checks_bitmap = _CHECK_TERMINAL_STATE
        if backend_revision:
            checks_bitmap |= _CHECK_BACKEND_REVISION
        else:
            anomalies.append("backend_revision_unattested")

        if canonical_hash(job_spec) == job_spec_hash:
            checks_bitmap |= _CHECK_JOB_SPEC_HASH
        else:
            anomalies.append("job_spec_hash_mismatch")

        if (
            isinstance(execution_plan, dict)
            and execution_plan_hash
            and canonical_hash(execution_plan) == execution_plan_hash
        ):
            checks_bitmap |= _CHECK_EXECUTION_PLAN_HASH
        else:
            anomalies.append("execution_plan_missing_or_changed")

        embedded_run_spec = job_spec.get("run_spec")
        if (
            isinstance(embedded_run_spec, dict)
            and run_spec_hash
            and canonical_hash(embedded_run_spec) == run_spec_hash
        ):
            checks_bitmap |= _CHECK_RUN_SPEC_HASH
        else:
            anomalies.append("runspec_missing_or_changed")

        result_summary_hash = (
            canonical_hash(result_summary) if result_summary is not None else ""
        )
        if terminal_status == "succeeded":
            if result_summary is None:
                anomalies.append("succeeded_without_result")
            if error is not None:
                anomalies.append("succeeded_with_error")
            if worker_exitcode not in {None, 0}:
                anomalies.append("succeeded_after_worker_crash")
            if not any(code.startswith("succeeded_") for code in anomalies):
                checks_bitmap |= _CHECK_RESULT_STATE
        elif terminal_status == "failed":
            if error is None:
                anomalies.append("failed_without_error")
            else:
                checks_bitmap |= _CHECK_RESULT_STATE
                if str(error.get("code") or "") == "worker_crashed":
                    anomalies.append("worker_crashed")
        else:
            checks_bitmap |= _CHECK_RESULT_STATE

        artifact_manifest_hash = canonical_hash(artifact_manifest)
        if all(
            item["state"] != "active" or bool(item["content_hash"])
            for item in artifact_manifest
        ):
            checks_bitmap |= _CHECK_ARTIFACT_HASHES
        else:
            anomalies.append("active_artifact_without_hash")

        explicit_integrity_anomalies = {
            "job_spec_hash_mismatch",
            "active_artifact_without_hash",
        }
        if terminal_status == "succeeded" and anomalies:
            disposition = "maintenance_required"
        elif (
            any(code in explicit_integrity_anomalies for code in anomalies)
            or (
                terminal_status == "failed"
                and str((error or {}).get("code") or "") == "worker_crashed"
            )
        ):
            disposition = "maintenance_required"
        elif terminal_status == "succeeded":
            disposition = "trusted"
        else:
            disposition = "not_usable"

        return TerminalAssuranceSummary(
            policy_hash=self.policy_hash,
            backend_revision=backend_revision or "unattested",
            run_spec_hash=run_spec_hash,
            checks_bitmap=checks_bitmap,
            anomaly_codes=tuple(anomalies),
            result_summary_hash=result_summary_hash,
            artifact_manifest_hash=artifact_manifest_hash,
            disposition=disposition,
        )
