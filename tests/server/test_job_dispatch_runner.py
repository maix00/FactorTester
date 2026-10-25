from __future__ import annotations

from server.jobs.dispatch import DispatchMessage, DispatchOutbox
from server.jobs.dispatch.dispatcher import DispatchRunner


def _message(job_id: str = "job-1") -> DispatchMessage:
    return DispatchMessage(
        job_id=job_id,
        attempt=1,
        deployment_id="remote-main",
        run_spec_hash="a" * 64,
        job_spec_hash="b" * 64,
    )


class _Publisher:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.messages: list[DispatchMessage] = []

    def publish(self, message: DispatchMessage) -> None:
        if self.fail:
            raise ConnectionError("broker unavailable")
        self.messages.append(message)


def test_runner_publishes_then_marks_sent(tmp_path):
    outbox = DispatchOutbox(tmp_path / "jobs.db")
    outbox.enqueue(_message(), now=100.0)
    publisher = _Publisher()
    result = DispatchRunner(outbox, publisher).run_once(limit=1)
    assert result == {"claimed": 1, "sent": 1, "failed": 0}
    assert publisher.messages == [_message()]
    assert outbox.get(("job-1", 1)).status == "sent"


def test_runner_failure_backs_off_not_sent(tmp_path):
    outbox = DispatchOutbox(tmp_path / "jobs.db", max_attempts=2)
    outbox.enqueue(_message(), now=100.0)
    result = DispatchRunner(outbox, _Publisher(fail=True)).run_once(limit=1)
    assert result["failed"] == 1
    record = outbox.get(("job-1", 1))
    assert record.status == "failed"
    assert record.attempts == 1
