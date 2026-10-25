from __future__ import annotations

from server.jobs.dispatch.celery_app import execute_plan_payload
from server.jobs.dispatch.contract import DispatchMessage
from server.jobs.dispatch.planning import PlanningDispatcher
from server.jobs.models import JobRecord
from server.jobs.repository.sqlite import JobRepository
from server.jobs.states import JobStatus


def _job(tmp_path, monkeypatch, *, kind="factor_evaluation"):
    monkeypatch.setenv("FACTORTESTER_DEPLOYMENT_ID", "local")
    repository = JobRepository(tmp_path / "jobs.db")
    repository.create(JobRecord(
        job_id="plan-job", run_id="run", owner="owner", workspace_id="ws",
        kind=kind, status=JobStatus.SUBMITTED, deployment_id="local",
        service_port=8001, run_spec_hash="a" * 64, job_spec={"run_spec": {}},
    ))
    return repository


class _Publisher:
    def __init__(self):
        self.messages = []

    def publish_plan(self, message):
        self.messages.append(message)


def test_planning_dispatcher_claims_and_publishes(tmp_path, monkeypatch):
    repository = _job(tmp_path, monkeypatch)
    publisher = _Publisher()
    result = PlanningDispatcher(repository, publisher).run_once()
    assert result["sent"] == 1
    assert publisher.messages[0].job_id == "plan-job"
    assert repository.require("plan-job").status is JobStatus.PLANNING


def test_plan_payload_persists_plan_and_queues_execution(tmp_path, monkeypatch):
    repository = _job(tmp_path, monkeypatch)
    assert repository.claim_planning("plan-job", 1) is not None
    message = DispatchMessage("plan-job", 1, "local", "a" * 64, "b" * 64, 8001)
    def planner(payload, sink, cancel):
        sink.emit_plan({"plan": {"plan_version": 1}, "notices": []})
    result = execute_plan_payload(message.to_dict(), repository=repository, planner=planner)
    assert result["status"] == "planned"
    job = repository.require("plan-job")
    assert job.status is JobStatus.QUEUED
    assert job.execution_plan == {"plan_version": 1}


def test_scheduler_can_yield_planning_and_execution_to_celery(monkeypatch, tmp_path):
    from server.jobs.scheduling.daemon import ResearchJobScheduler
    from server.jobs.states import JobStatus

    monkeypatch.setenv("FACTORTESTER_DEPLOYMENT_ID", "local")
    monkeypatch.setenv("FACTORTESTER_CELERY_PLANNING", "1")
    monkeypatch.setenv("FACTORTESTER_CELERY_EXECUTION", "1")
    repository = JobRepository(tmp_path / "jobs.db")
    scheduler = ResearchJobScheduler(repository=repository, deployment_id="local")
    scheduler._dispatch_planning()
    scheduler._dispatch_execution()
    assert repository.list_for_deployment(
        deployment_id="local", statuses=(JobStatus.QUEUED,),
    ) == []
