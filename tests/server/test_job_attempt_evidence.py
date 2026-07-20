"""Fail-closed JobAttempt EvidenceEnvelope projection tests."""

from __future__ import annotations

from dataclasses import replace

import pytest

from server.jobs.assurance import TerminalAssuranceSummary
from server.jobs.models import JobRecord
from server.jobs.states import JobStatus
from server.services.research_graph.research_cycle.job_evidence import (
    project_job_attempt_evidence,
)


IDENTITY = {
    "contract_hash": "1" * 64,
    "methodology_hash": "2" * 64,
    "trial_plan_hash": "3" * 64,
    "run_spec_hash": "4" * 64,
}


def _job(
    *,
    status: JobStatus = JobStatus.SUCCEEDED,
    disposition: str = "trusted",
    anomalies: tuple[str, ...] = (),
    run_spec_hash: str = "4" * 64,
) -> JobRecord:
    return JobRecord(
        job_id="job-1",
        run_id="run-1",
        owner="alice",
        workspace_id="workspace-1",
        kind="ic",
        status=status,
        source_revision="backend-1",
        attempt=2,
        terminal_assurance=TerminalAssuranceSummary(
            policy_hash="7" * 64,
            backend_revision="backend-1",
            run_spec_hash=run_spec_hash,
            checks_bitmap=127,
            anomaly_codes=anomalies,
            result_summary_hash="5" * 64,
            artifact_manifest_hash="6" * 64,
            disposition=disposition,
        ),
    )


@pytest.mark.parametrize(
    ("job", "identity"),
    [
        (replace(_job(), status=JobStatus.RUNNING), IDENTITY),
        (_job(), None),
        (_job(run_spec_hash="8" * 64), IDENTITY),
    ],
)
def test_job_attempt_projection_rejects_unqualified_inputs(
    job: JobRecord,
    identity: dict[str, str] | None,
) -> None:
    assert project_job_attempt_evidence(
        job,
        identity_refs=identity,
        trial_stage="selection",
    ) is None


@pytest.mark.parametrize(
    ("status", "disposition", "anomalies"),
    [
        (JobStatus.FAILED, "not_usable", ("failed_without_error",)),
        (
            JobStatus.SUCCEEDED,
            "maintenance_required",
            ("succeeded_after_worker_crash",),
        ),
    ],
)
def test_job_attempt_projection_preserves_terminal_assurance_facts(
    status: JobStatus,
    disposition: str,
    anomalies: tuple[str, ...],
) -> None:
    envelope = project_job_attempt_evidence(
        _job(
            status=status,
            disposition=disposition,
            anomalies=anomalies,
        ),
        identity_refs=IDENTITY,
        trial_stage="selection",
    )

    assert envelope is not None
    assert envelope["facts"]["status"] == status.value
    assert envelope["facts"]["assurance"]["disposition"] == disposition
    assert envelope["facts"]["assurance"]["anomaly_codes"] == list(anomalies)
    assert "result_summary" not in envelope


def test_only_named_net_return_artifact_certifies_return_series() -> None:
    generic = project_job_attempt_evidence(
        _job(),
        identity_refs=IDENTITY,
        trial_stage="selection",
        active_artifacts=[{
            "name": "result",
            "content_hash": "9" * 64,
            "content_type": "application/json",
            "size_bytes": 24,
        }],
    )
    named = project_job_attempt_evidence(
        _job(),
        identity_refs=IDENTITY,
        trial_stage="selection",
        active_artifacts=[{
            "name": "net_returns",
            "content_hash": "9" * 64,
            "content_type": "application/x-parquet",
            "size_bytes": 24,
        }],
    )

    assert generic is not None
    assert generic["facts"]["net_return_series_available"] is False
    assert "artifact:net_returns:sha256:" not in " ".join(
        generic["artifact_refs"]
    )
    assert named is not None
    assert named["facts"]["net_return_series_available"] is True
    assert named["facts"]["net_return_series_ref"] == (
        "artifact:net_returns:sha256:" + "9" * 64
    )
    assert named["artifact_refs"] == [
        "artifact-manifest:sha256:" + "6" * 64,
        "artifact:net_returns:sha256:" + "9" * 64,
    ]
