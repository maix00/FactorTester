from __future__ import annotations

from server.jobs.dispatch import DispatchOutbox
from server.jobs.dispatch import service


def test_build_runner_uses_job_db_and_preflight(tmp_path, monkeypatch):
    calls = []

    class _Publisher:
        def publish(self, message):
            calls.append(message)

    monkeypatch.setenv("FACTORTESTER_JOB_DB", str(tmp_path / "jobs.db"))
    monkeypatch.setenv("FACTORTESTER_BROKER_URL", "memory://")
    monkeypatch.setattr(service, "publisher_from_env", lambda: _Publisher())
    monkeypatch.setattr(service, "resolve_executor", lambda: object())
    runner = service.build_runner()
    assert runner.outbox.db_path == tmp_path / "jobs.db"
    assert runner.preflight is not None
    DispatchOutbox(tmp_path / "jobs.db").ensure_schema()
