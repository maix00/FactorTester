"""Single-host scheduler for durable research jobs and isolated workers."""

from __future__ import annotations

import threading
import time
from typing import Any

from server.jobs.events import EventBroker
from server.jobs.repository import JobRepository
from server.jobs.states import JobStatus

from .worker_pool import LongLivedWorkerPool, WorkerUnavailable


PLANNER_RUNNER = "server.jobs.planning.runners:plan_job"


class ResearchJobScheduler:
    """Drive durable job facts while keeping live events process-local."""

    def __init__(
        self,
        *,
        repository: JobRepository,
        deployment_id: str,
        planner_workers: int = 1,
        execution_workers: int = 2,
        broker: EventBroker | None = None,
        cancel_grace_seconds: float = 2.0,
    ) -> None:
        self.repository = repository
        self.deployment_id = str(deployment_id)
        self.broker = broker or EventBroker()
        self.planners = LongLivedWorkerPool(
            size=planner_workers,
            cancel_grace_seconds=cancel_grace_seconds,
        )
        self.executors = LongLivedWorkerPool(
            size=execution_workers,
            cancel_grace_seconds=cancel_grace_seconds,
        )
        self._planning: set[str] = set()
        self._executing: set[str] = set()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._recover_interrupted_jobs()

    def _recover_interrupted_jobs(self) -> None:
        interrupted = self.repository.list_for_deployment(
            deployment_id=self.deployment_id,
            statuses=(JobStatus.PLANNING, JobStatus.RUNNING, JobStatus.PAUSED),
        )
        for job in interrupted:
            self.repository.transition(
                job.job_id,
                JobStatus.FAILED,
                expected=job.status,
                error={
                    "code": "scheduler_restarted",
                    "message": "scheduler restarted while the job owned a worker",
                },
            )

    def start(self, *, poll_interval: float = 0.05) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._serve,
            args=(max(0.01, float(poll_interval)),),
            daemon=True,
            name="research-job-scheduler",
        )
        self._thread.start()

    def _serve(self, poll_interval: float) -> None:
        while not self._stop.wait(poll_interval):
            self.tick()

    def tick(self) -> None:
        self._drain_pool(self.planners, stage="planning")
        self._drain_pool(self.executors, stage="execution")
        self._propagate_cancellation()
        self._dispatch_planning()
        self._dispatch_execution()

    def _dispatch_planning(self) -> None:
        jobs = self.repository.list_for_deployment(
            deployment_id=self.deployment_id,
            statuses=(JobStatus.SUBMITTED,),
        )
        for job in jobs:
            try:
                self.planners.submit(
                    job_id=job.job_id,
                    runner_path=PLANNER_RUNNER,
                    payload={
                        "job_spec": job.job_spec,
                        "runner_path": job.runner_path,
                    },
                )
            except WorkerUnavailable:
                return
            self.repository.transition(
                job.job_id,
                JobStatus.PLANNING,
                expected=JobStatus.SUBMITTED,
            )
            self._planning.add(job.job_id)
            self.broker.publish(job.job_id, "status", {"status": "planning"})

    def _dispatch_execution(self) -> None:
        jobs = self.repository.list_for_deployment(
            deployment_id=self.deployment_id,
            statuses=(JobStatus.QUEUED,),
        )
        jobs.sort(key=lambda job: (not self.repository.is_pinned(job.job_id), job.created_at))
        active_by_owner: dict[str, int] = {}
        for active_id in self._executing:
            active = self.repository.load(active_id)
            if active is not None:
                active_by_owner[active.owner] = active_by_owner.get(active.owner, 0) + 1
        for job in jobs:
            if active_by_owner.get(job.owner, 0) >= job.entitlement.max_concurrency:
                continue
            plan = job.execution_plan or {}
            try:
                pid = self.executors.submit(
                    job_id=job.job_id,
                    runner_path=job.runner_path,
                    payload={**job.job_spec, "execution_plan": plan},
                    cache_keys=list(plan.get("cache_keys") or []),
                    pinned=self.repository.is_pinned(job.job_id),
                )
            except WorkerUnavailable:
                return
            self.repository.transition(
                job.job_id,
                JobStatus.RUNNING,
                expected=JobStatus.QUEUED,
                worker_pid=pid,
            )
            self._executing.add(job.job_id)
            active_by_owner[job.owner] = active_by_owner.get(job.owner, 0) + 1
            self.broker.publish(job.job_id, "status", {"status": "running", "worker_pid": pid})

    def _propagate_cancellation(self) -> None:
        for job_id, pool in (
            *((job_id, self.planners) for job_id in tuple(self._planning)),
            *((job_id, self.executors) for job_id in tuple(self._executing)),
        ):
            job = self.repository.load(job_id)
            if job is not None and job.cancel_requested_at is not None:
                pool.request_cancel(job_id)

    def _drain_pool(self, pool: LongLivedWorkerPool, *, stage: str) -> None:
        for message in pool.poll(timeout=0.0):
            job_id = str(message.get("job_id") or "")
            if not job_id:
                continue
            if message.get("type") == "event":
                self._handle_event(job_id, str(message.get("event") or ""), dict(message.get("data") or {}), stage=stage)
            elif message.get("type") in {"worker_crashed", "worker_terminated"}:
                self._handle_worker_loss(job_id, message, stage=stage)
            elif message.get("type") == "task_finished":
                if stage == "planning":
                    self._planning.discard(job_id)
                else:
                    self._executing.discard(job_id)

    def _handle_event(self, job_id: str, event: str, data: dict[str, Any], *, stage: str) -> None:
        self.broker.publish(job_id, event, data)
        job = self.repository.load(job_id)
        if job is None:
            return
        if event == "result" and stage == "planning" and job.status is JobStatus.PLANNING:
            self.repository.set_execution_plan(
                job_id,
                plan=dict(data.get("plan") or {}),
                notices=list(data.get("notices") or []),
                requires_confirmation=bool(data.get("requires_confirmation")),
            )
            return
        if event == "result" and stage == "execution" and job.status is JobStatus.RUNNING:
            summary = dict(data)
            self.repository.transition(
                job_id,
                JobStatus.SUCCEEDED,
                expected=JobStatus.RUNNING,
                result_summary=summary,
            )
            self.broker.close(job_id)
            return
        if event != "error":
            return
        cancelled = bool(data.get("cancelled")) or job.cancel_requested_at is not None
        target = JobStatus.CANCELLED if cancelled else JobStatus.FAILED
        if job.status in {JobStatus.PLANNING, JobStatus.RUNNING}:
            self.repository.transition(
                job_id,
                target,
                expected=job.status,
                cancel_reason=job.cancel_reason if cancelled else "",
                error=data,
            )
            self.broker.close(job_id)

    def _handle_worker_loss(self, job_id: str, message: dict[str, Any], *, stage: str) -> None:
        job = self.repository.load(job_id)
        if job is None or job.status not in {JobStatus.PLANNING, JobStatus.RUNNING}:
            return
        cancelled = job.cancel_requested_at is not None
        self.repository.transition(
            job_id,
            JobStatus.CANCELLED if cancelled else JobStatus.FAILED,
            expected=job.status,
            worker_exitcode=message.get("worker_exitcode"),
            cancel_reason=job.cancel_reason if cancelled else "",
            error={
                "code": "worker_terminated" if cancelled else "worker_crashed",
                "message": "worker stopped before producing a terminal result",
                "stage": stage,
                "worker_pid": message.get("worker_pid"),
                "worker_exitcode": message.get("worker_exitcode"),
            },
        )
        self.broker.publish(job_id, "error", self.repository.require(job_id).error or {})
        self.broker.close(job_id)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self.planners.close()
        self.executors.close()

    def __enter__(self) -> "ResearchJobScheduler":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()
