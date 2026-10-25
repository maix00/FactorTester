from __future__ import annotations

from scripts.test.job_dispatch_smoke import create_probe
from server.jobs.dispatch import DispatchOutbox
from server.jobs.repository.sqlite import JobRepository


def test_create_probe_enqueues_only_target_port(tmp_path):
    db = tmp_path / "jobs.db"
    repository = JobRepository(db)
    create_probe(repository, job_id="probe-8001", deployment="local-docker", port=8001)
    outbox = DispatchOutbox(db)
    record = outbox.get(("probe-8001", 1))
    assert record is not None
    assert record.message.service_port == 8001
    assert record.message.deployment_id == "local-docker"
    assert repository.require("probe-8001").status.value == "queued"
