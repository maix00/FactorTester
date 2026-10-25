from __future__ import annotations

import sqlite3

import pytest

from server.jobs.dispatch import (
    DispatchMessage,
    DispatchOutbox,
    DispatchSchemaError,
)
from server.jobs.dispatch.contract import SCHEMA_VERSION


def _message(job_id: str = "job-1", attempt: int = 1) -> DispatchMessage:
    return DispatchMessage(
        job_id=job_id,
        attempt=attempt,
        deployment_id="remote-main",
        run_spec_hash="a" * 64,
        job_spec_hash="b" * 64,
    )


def test_dispatch_message_rejects_unsafe_or_unversioned_payload():
    with pytest.raises(DispatchSchemaError):
        DispatchMessage("bad/id", 1, "remote-main", "a" * 64, "b" * 64)
    with pytest.raises(DispatchSchemaError):
        DispatchMessage("job", 0, "remote-main", "a" * 64, "b" * 64)
    with pytest.raises(DispatchSchemaError):
        DispatchMessage("job", 1, "remote-main", "not-a-hash", "b" * 64)
    payload = _message().to_dict()
    payload["schema_version"] = SCHEMA_VERSION + 1
    with pytest.raises(DispatchSchemaError):
        DispatchMessage.from_dict(payload)


def test_dispatch_message_roundtrip_is_stable():
    message = _message()
    assert DispatchMessage.from_dict(message.to_dict()) == message
    assert message.digest() == _message().digest()
    assert message.identity == ("job-1", 1)


def test_outbox_enqueue_is_idempotent(tmp_path):
    outbox = DispatchOutbox(tmp_path / "jobs.db")
    message = _message()
    outbox.enqueue(message)
    outbox.enqueue(message)
    assert outbox.counts()["pending"] == 1
    record = outbox.get(("job-1", 1))
    assert record is not None
    assert record.message == message
    assert record.attempts == 0


def test_claim_leases_once_and_marks_sent(tmp_path):
    outbox = DispatchOutbox(tmp_path / "jobs.db", lease_seconds=60)
    outbox.enqueue(_message(), now=100.0)
    first = outbox.claim(limit=1, now=100.0)
    assert len(first) == 1
    assert outbox.claim(limit=1, now=101.0) == []
    outbox.mark_sent(first[0].identity, now=102.0)
    assert outbox.get(("job-1", 1)).status == "sent"
    assert outbox.counts()["sent"] == 1


def test_expired_lease_is_reclaimable(tmp_path):
    outbox = DispatchOutbox(tmp_path / "jobs.db", lease_seconds=10)
    outbox.enqueue(_message(), now=100.0)
    assert len(outbox.claim(limit=1, now=100.0)) == 1
    assert outbox.claim(limit=1, now=109.0) == []
    reclaimed = outbox.claim(limit=1, now=110.0)
    assert len(reclaimed) == 1
    assert reclaimed[0].attempts == 2


def test_failure_backoff_and_dead_after_max_attempts(tmp_path):
    outbox = DispatchOutbox(tmp_path / "jobs.db", max_attempts=2)
    outbox.enqueue(_message(), now=100.0)
    first = outbox.claim(limit=1, now=100.0)[0]
    assert outbox.mark_failed(first.identity, "broker down", now=101.0, retry_delay=5) == "failed"
    assert outbox.claim(limit=1, now=104.0) == []
    second = outbox.claim(limit=1, now=106.0)[0]
    assert second.attempts == 2
    assert outbox.mark_failed(second.identity, "still down", now=107.0) == "dead"
    assert outbox.claim(limit=1, now=1000.0) == []
    assert outbox.counts()["dead"] == 1


def test_claims_respect_created_order_and_limit(tmp_path):
    outbox = DispatchOutbox(tmp_path / "jobs.db")
    outbox.enqueue(_message("job-a"), now=100.0)
    outbox.enqueue(_message("job-b"), now=101.0)
    rows = outbox.claim(limit=2, now=110.0)
    assert [row.job_id for row in rows] == ["job-a", "job-b"]


def test_claim_keeps_attempt_identity_unique(tmp_path):
    outbox = DispatchOutbox(tmp_path / "jobs.db")
    outbox.enqueue(_message(attempt=1))
    outbox.enqueue(_message(attempt=2))
    assert outbox.counts()["pending"] == 2
    identities = {row.identity for row in outbox.claim(limit=2)}
    assert identities == {("job-1", 1), ("job-1", 2)}


def test_mark_failed_unknown_identity_raises(tmp_path):
    outbox = DispatchOutbox(tmp_path / "jobs.db")
    with pytest.raises(KeyError):
        outbox.mark_failed(("missing", 1), "boom")


def test_repository_queues_dispatch_in_same_transaction(tmp_path):
    from server.jobs.models import JobRecord
    from server.jobs.repository.sqlite import JobRepository
    from server.jobs.states import JobStatus

    repository = JobRepository(tmp_path / "jobs.db")
    record = JobRecord(
        job_id="job-tx",
        run_id="run-tx",
        owner="owner",
        workspace_id="workspace",
        kind="backtest",
        status=JobStatus.SUBMITTED,
        deployment_id="remote-main",
        run_spec_hash="c" * 64,
        job_spec={"analysis": "backtest"},
    )
    repository.create(record)
    repository.transition("job-tx", JobStatus.PLANNING)
    repository.transition("job-tx", JobStatus.QUEUED)

    outbox = DispatchOutbox(tmp_path / "jobs.db")
    row = outbox.get(("job-tx", 1))
    assert row is not None
    assert row.status == "pending"
    assert row.message.run_spec_hash == "c" * 64
    assert row.message.deployment_id == "remote-main"


def test_repository_does_not_queue_legacy_job_without_run_spec(tmp_path):
    from server.jobs.models import JobRecord
    from server.jobs.repository.sqlite import JobRepository
    from server.jobs.states import JobStatus

    repository = JobRepository(tmp_path / "jobs.db")
    repository.create(
        JobRecord(
            job_id="job-legacy",
            run_id="run-legacy",
            owner="owner",
            workspace_id="workspace",
            kind="backtest",
            status=JobStatus.SUBMITTED,
            deployment_id="remote-main",
            run_spec_hash="",
            job_spec={},
        )
    )
    repository.transition("job-legacy", JobStatus.PLANNING)
    repository.transition("job-legacy", JobStatus.QUEUED)
    outbox = DispatchOutbox(tmp_path / "jobs.db")
    assert outbox.get(("job-legacy", 1)) is None


def test_claim_attempt_is_idempotent(tmp_path):
    from server.jobs.models import JobRecord
    from server.jobs.repository.sqlite import JobRepository
    from server.jobs.states import JobStatus

    repository = JobRepository(tmp_path / "jobs.db")
    repository.create(
        JobRecord(
            job_id="job-claim",
            run_id="run-claim",
            owner="owner",
            workspace_id="workspace",
            kind="backtest",
            status=JobStatus.SUBMITTED,
            deployment_id="remote-main",
            run_spec_hash="d" * 64,
            job_spec={},
        )
    )
    repository.transition("job-claim", JobStatus.PLANNING)
    repository.transition("job-claim", JobStatus.QUEUED)
    first = repository.claim_attempt("job-claim", 1, worker_pid=123)
    assert first is not None
    assert first.status is JobStatus.RUNNING
    assert first.worker_pid == 123
    assert repository.claim_attempt("job-claim", 1, worker_pid=456) is None
    assert repository.claim_attempt("job-claim", 2, worker_pid=456) is None


def test_cancelling_queued_job_closes_outbox_row(tmp_path):
    from server.jobs.models import JobRecord
    from server.jobs.repository.sqlite import JobRepository
    from server.jobs.states import JobStatus

    repository = JobRepository(tmp_path / "jobs.db")
    repository.create(
        JobRecord(
            job_id="job-cancel",
            run_id="run-cancel",
            owner="owner",
            workspace_id="workspace",
            kind="backtest",
            status=JobStatus.SUBMITTED,
            deployment_id="remote-main",
            run_spec_hash="e" * 64,
            job_spec={},
        )
    )
    repository.transition("job-cancel", JobStatus.PLANNING)
    repository.transition("job-cancel", JobStatus.QUEUED)
    outbox = DispatchOutbox(tmp_path / "jobs.db")
    assert outbox.get(("job-cancel", 1)).status == "pending"
    repository.request_cancel("job-cancel", owner="owner", reason="user")
    assert outbox.get(("job-cancel", 1)).status == "dead"


def test_non_backtest_job_is_not_dispatched(tmp_path):
    from server.jobs.models import JobRecord
    from server.jobs.repository.sqlite import JobRepository
    from server.jobs.states import JobStatus

    repository = JobRepository(tmp_path / "jobs.db")
    repository.create(
        JobRecord(
            job_id="job-ic",
            run_id="run-ic",
            owner="owner",
            workspace_id="workspace",
            kind="ic",
            status=JobStatus.SUBMITTED,
            deployment_id="remote-main",
            run_spec_hash="f" * 64,
            job_spec={},
        )
    )
    repository.transition("job-ic", JobStatus.PLANNING)
    repository.transition("job-ic", JobStatus.QUEUED)
    assert DispatchOutbox(tmp_path / "jobs.db").get(("job-ic", 1)) is None


def test_worker_lease_heartbeat_and_expiry_fails_job(tmp_path):
    from server.jobs.models import JobRecord
    from server.jobs.repository.sqlite import JobRepository
    from server.jobs.states import JobStatus

    repository = JobRepository(tmp_path / "jobs.db")
    repository.create(
        JobRecord(
            job_id="job-lease",
            run_id="run-lease",
            owner="owner",
            workspace_id="workspace",
            kind="backtest",
            status=JobStatus.SUBMITTED,
            deployment_id="remote-main",
            run_spec_hash="1" * 64,
            job_spec={},
        )
    )
    repository.transition("job-lease", JobStatus.PLANNING)
    repository.transition("job-lease", JobStatus.QUEUED)
    claimed = repository.claim_attempt("job-lease", 1, worker_id="worker-a")
    assert claimed is not None
    assert repository.heartbeat_attempt("job-lease", 1, "worker-a", lease_seconds=60)
    assert not repository.heartbeat_attempt("job-lease", 1, "worker-b", lease_seconds=60)
    failed = repository.recover_expired_leases(now=claimed.started_at + 31)
    assert failed == []
    expired = repository.recover_expired_leases(now=claimed.started_at + 10_000)
    assert expired == ["job-lease"]
    record = repository.require("job-lease")
    assert record.status is JobStatus.FAILED
    assert record.error["code"] == "worker_lease_expired"
