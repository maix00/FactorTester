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
