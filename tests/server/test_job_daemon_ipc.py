from __future__ import annotations

import threading
import time

from server.jobs.ipc import JobDaemonClient, JobDaemonServer
from server.jobs.models import JobRecord
from server.jobs.repository import JobRepository
from server.jobs.scheduling import ResearchJobScheduler
from server.jobs.states import JobStatus


def test_unix_socket_exposes_health_wake_events_and_cancel(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    repository.create(JobRecord(
        job_id="ipc-job",
        run_id="run-ipc",
        owner="alice",
        workspace_id="workspace-1",
        kind="fake",
        status=JobStatus.SUBMITTED,
        deployment_id="ipc-test",
        runner_path="tests.server.long_lived_worker_fakes:blocking_runner",
        job_spec={"seconds": 30},
        created_at=time.time(),
    ))
    scheduler = ResearchJobScheduler(
        repository=repository,
        deployment_id="ipc-test",
        planner_workers=1,
        execution_workers=1,
    )
    server = JobDaemonServer(socket_path=tmp_path / "jobs.sock", scheduler=scheduler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = JobDaemonClient(tmp_path / "jobs.sock")
    try:
        health = client.health()
        assert health["deployment_id"] == "ipc-test"
        client.wake()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            current = repository.require("ipc-job")
            if current.status is JobStatus.RUNNING:
                break
            client.wake()
            time.sleep(0.02)
        assert repository.require("ipc-job").status is JobStatus.RUNNING
        snapshot = client.events("ipc-job", after=0, timeout=0)
        assert any(row["event"] == "status" for row in snapshot["events"])
        repository.request_cancel("ipc-job", owner="alice", reason="explicit_cancel")
        client.cancel("ipc-job")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            client.wake()
            if repository.require("ipc-job").status is JobStatus.CANCELLED:
                break
            time.sleep(0.02)
        assert repository.require("ipc-job").status is JobStatus.CANCELLED
    finally:
        server.server.shutdown()
        thread.join(timeout=3)
