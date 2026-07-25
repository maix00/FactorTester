from __future__ import annotations

from server.jobs.models import JobRecord
from server.jobs.repository import JobRepository
from server.jobs.states import JobStatus


def test_job_port_is_persisted_but_deployment_is_not_public(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    record = repository.create(JobRecord(
        job_id="job-port",
        run_id="run-port",
        owner="alice",
        workspace_id="workspace-port",
        kind="backtest",
        status=JobStatus.SUBMITTED,
        deployment_id="internal-deployment",
        service_port=8142,
        job_spec={"run_spec": {}},
    ))

    loaded = repository.require("job-port", owner="alice")
    assert loaded.service_port == 8142
    assert record.summary()["port"] == 8142
    assert "deployment_id" not in record.summary()


def test_job_list_can_filter_by_port(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    for job_id, port in (("job-a", 8141), ("job-b", 8142)):
        repository.create(JobRecord(
            job_id=job_id,
            run_id=job_id,
            owner="alice",
            workspace_id="workspace-port",
            kind="ic",
            status=JobStatus.SUBMITTED,
            service_port=port,
            job_spec={},
        ))

    rows = repository.list_with_metadata(
        owner="alice", service_port=8142, limit=20,
    )
    assert [item["job"].job_id for item in rows] == ["job-b"]
