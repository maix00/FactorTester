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
        service_port=8001,
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
    assert result == {"claimed": 1, "sent": 1, "failed": 0, "deferred": 0}
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


def test_preflight_failure_does_not_claim_or_publish(tmp_path):
    import pytest

    outbox = DispatchOutbox(tmp_path / "jobs.db")
    outbox.enqueue(_message(), now=100.0)

    def unavailable() -> None:
        raise RuntimeError("no Nautilus executor")

    publisher = _Publisher()
    with pytest.raises(RuntimeError):
        DispatchRunner(outbox, publisher, preflight=unavailable).run_once(limit=1)
    assert publisher.messages == []
    assert outbox.get(("job-1", 1)).status == "pending"
    assert outbox.get(("job-1", 1)).attempts == 0


def test_kombu_publisher_uses_celery_protocol_and_target_queue(monkeypatch):
    import celery

    from server.jobs.dispatch.dispatcher import KombuPublisher

    captured = {}

    class FakeApp:
        def __init__(self, name, broker):
            captured["broker"] = broker

        def send_task(self, task, **kwargs):
            captured["task"] = task
            captured["kwargs"] = kwargs

    monkeypatch.setattr(celery, "Celery", FakeApp)
    publisher = KombuPublisher("amqp://guest:guest@localhost//", queue="factortester.jobs")
    message = _message("job-publish")
    publisher.publish(message)
    assert captured["task"] == "factortester.execute_job"
    kwargs = captured["kwargs"]
    assert kwargs["queue"].name == "factortester.jobs.remote-main.8001"
    assert kwargs["routing_key"] == "factortester.jobs.remote-main.8001"
    assert kwargs["exchange"].name == "factortester"
    assert kwargs["serializer"] == "json"


def test_offline_target_is_deferred_not_published(tmp_path):
    outbox = DispatchOutbox(tmp_path / "jobs.db")
    outbox.enqueue(_message("job-offline"), now=100.0)
    publisher = _Publisher()
    runner = DispatchRunner(
        outbox, publisher, target_online=lambda deployment, port: False,
    )
    result = runner.run_once(limit=1)
    assert result["deferred"] == 1
    assert publisher.messages == []
    row = outbox.get(("job-offline", 1))
    assert row.status == "pending"
    assert row.attempts == 0
