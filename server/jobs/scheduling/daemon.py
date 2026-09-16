"""Single-host scheduler for durable research jobs and isolated workers."""

from __future__ import annotations

import os

import threading
import time
import logging
from typing import Any

from server.jobs.events import EventBroker
from server.jobs.artifacts import artifact_root, default_user_quota_bytes
from server.jobs.repository import JobRepository
from server.jobs.states import JobStatus

from .worker_pool import (
    env_positive_int,
    LongLivedWorkerPool,
    WorkerUnavailable,
    persisted_result_summary,
)


_LOGGER = logging.getLogger(__name__)


PLANNER_RUNNER = "server.jobs.planning.runners:plan_job"

_PRIORITY_CLASS_RANK = {"low": 0, "standard": 10, "high": 20, "admin": 30}


class ResearchJobScheduler:
    """Drive durable job facts while keeping live events process-local."""

    def __init__(
        self,
        *,
        repository: JobRepository,
        deployment_id: str,
        planner_workers: int | None = None,
        execution_workers: int | None = None,
        broker: EventBroker | None = None,
        cancel_grace_seconds: float = 2.0,
        result_artifact_root: str | None = None,
    ) -> None:
        if planner_workers is None:
            planner_workers = env_positive_int("GTHT_JOB_PLANNER_WORKERS", 1)
        if execution_workers is None:
            # Concurrency is a memory and CPU budget, not a target: each
            # execution worker can hold its own working set, and the website
            # shares the host.  Keep the default small and let a host opt up.
            execution_workers = env_positive_int("GTHT_JOB_EXECUTION_WORKERS", 2)
        self.repository = repository
        self.deployment_id = str(deployment_id)
        self.broker = broker or EventBroker()
        self.artifact_root = str(result_artifact_root or artifact_root())
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
        self._draining = False
        self._thread: threading.Thread | None = None
        self._tick_lock = threading.Lock()
        from server.services.transient_factor_sources import cleanup_stale_scopes
        from server.services.transient_strategy_sources import (
            cleanup_stale_scopes as cleanup_strategy_scopes,
        )

        cleanup_stale_scopes(self.repository)
        cleanup_strategy_scopes(self.repository)
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

    def start(self, *, poll_interval: float = 1.0) -> None:
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
        with self._tick_lock:
            self._drain_pool(self.planners, stage="planning")
            self._drain_pool(self.executors, stage="execution")
            self._propagate_cancellation()
            if self._draining:
                return
            self._dispatch_planning()
            self._dispatch_execution()

    def _dispatch_planning(self) -> None:
        jobs = self.repository.list_for_deployment(
            deployment_id=self.deployment_id,
            statuses=(JobStatus.SUBMITTED,),
        )
        for job in jobs:
            if job.job_role != "primary":
                continue
            try:
                self.planners.submit(
                    job_id=job.job_id,
                    runner_path=PLANNER_RUNNER,
                    payload={
                        # Planning validates source revisions.  Its runner
                        # needs the same top-level execution context as the
                        # final worker, notably the Profile owner and the
                        # opaque transient-source scope id.  Keeping those
                        # only inside ``job_spec`` makes preview succeed but
                        # makes a durable submitted Profile-factor job fail
                        # before its plan is built.
                        **job.job_spec,
                        "job_spec": job.job_spec,
                        "kind": job.kind,
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
        pending = self.repository.list_for_deployment(
            deployment_id=self.deployment_id,
            statuses=(
                JobStatus.SUBMITTED,
                JobStatus.PLANNING,
                JobStatus.AWAITING_CONFIRMATION,
                JobStatus.QUEUED,
                JobStatus.RUNNING,
                JobStatus.PAUSED,
            ),
        )
        pending_by_owner: dict[str, list[Any]] = {}
        for item in pending:
            pending_by_owner.setdefault(item.owner, []).append(item)
        queued_by_id = {job.job_id: job for job in jobs}
        candidates = []
        for owner, owner_jobs in pending_by_owner.items():
            pinned = queued_by_id.get(self.repository.pinned_job_id(owner=owner))
            if pinned is not None:
                candidates.append(pinned)
                continue
            for item in owner_jobs:
                if item.status in {JobStatus.RUNNING, JobStatus.PAUSED}:
                    continue
                if item.status is JobStatus.QUEUED:
                    candidates.append(item)
                break
        candidates.sort(key=self._cross_user_priority_key)
        active_by_owner: dict[str, int] = {}
        for active_id in self._executing:
            active = self.repository.load(active_id)
            if active is not None:
                active_by_owner[active.owner] = active_by_owner.get(active.owner, 0) + 1
        for job in candidates:
            pinned = self.repository.is_pinned(job.job_id)
            if active_by_owner.get(job.owner, 0) >= job.entitlement.max_concurrency:
                continue
            plan = job.execution_plan or {}
            try:
                pid = self.executors.submit(
                    job_id=job.job_id,
                    runner_path=job.runner_path,
                    payload={**job.job_spec, "execution_plan": plan},
                    cache_keys=list(plan.get("cache_keys") or []),
                    pinned=pinned,
                    artifact_root=self.artifact_root,
                    retention_mode=job.retention_mode,
                    artifact_job_id=(
                        job.parent_job_id
                        if job.job_role == "supplemental" else job.job_id
                    ),
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

    @staticmethod
    def _cross_user_priority_key(job: Any) -> tuple[Any, ...]:
        """Order owner candidates without allowing a personal pin to boost priority."""
        entitlement = job.entitlement
        return (
            -int(bool(entitlement.reserved_capacity_class)),
            -_PRIORITY_CLASS_RANK.get(entitlement.priority_class, 10),
            -float(entitlement.weight),
            float(job.created_at),
            str(job.owner),
            str(job.job_id),
        )

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
        if event not in {"artifact", "paused", "result", "error"}:
            self.broker.publish(job_id, event, data)
            return
        job = self.repository.load(job_id)
        if job is None:
            return
        if event == "result" and stage == "planning" and job.status is JobStatus.PLANNING:
            planned = self.repository.set_execution_plan(
                job_id,
                plan=dict(data.get("plan") or {}),
                notices=list(data.get("notices") or []),
                requires_confirmation=bool(data.get("requires_confirmation")),
            )
            self.broker.publish(job_id, "plan", {
                "status": planned.status.value,
                "execution_plan": planned.execution_plan,
                "notices": planned.plan_notices,
            })
            return
        self.broker.publish(job_id, event, data)
        if event == "artifact" and stage == "execution":
            artifact_job_id = (
                job.parent_job_id
                if job.job_role == "supplemental" else job_id
            )
            artifact_recorder = (
                self.repository.record_derived_artifact
                if job.job_role == "supplemental"
                else self.repository.record_artifact
            )
            artifact_recorder(
                job_id=artifact_job_id,
                name=str(data["name"]),
                relative_path=str(data["relative_path"]),
                content_type=str(data.get("content_type") or "application/octet-stream"),
                content_hash=str(data["content_hash"]),
                size_bytes=int(data["size_bytes"]),
            )
            self._enforce_storage_quota(job.owner)
            return
        if event == "paused" and stage == "execution" and job.status is JobStatus.RUNNING:
            self.repository.transition(
                job_id,
                JobStatus.PAUSED,
                expected=JobStatus.RUNNING,
            )
            return
        if event == "result" and stage == "execution" and job.status is JobStatus.RUNNING:
            if job.cancel_requested_at is not None:
                cancelled = self.repository.transition(
                    job_id,
                    JobStatus.CANCELLED,
                    expected=JobStatus.RUNNING,
                    cancel_reason=job.cancel_reason,
                    error={
                        "success": False,
                        "cancelled": True,
                        "code": "cancelled_before_result_commit",
                        "message": "cancellation was requested before the result was committed",
                    },
                )
                if cancelled.job_role == "primary":
                    self._register_terminal_evidence(cancelled)
                self.broker.close(job_id)
                return
            summary = persisted_result_summary(data)
            completed = self.repository.transition(
                job_id,
                JobStatus.SUCCEEDED,
                expected=JobStatus.RUNNING,
                result_summary=summary,
            )
            if completed.job_role == "primary":
                self._register_terminal_evidence(completed)
            self.broker.close(job_id)
            return
        if event != "error":
            return
        cancelled = bool(data.get("cancelled")) or job.cancel_requested_at is not None
        target = JobStatus.CANCELLED if cancelled else JobStatus.FAILED
        if job.status in {JobStatus.PLANNING, JobStatus.RUNNING}:
            completed = self.repository.transition(
                job_id,
                target,
                expected=job.status,
                cancel_reason=job.cancel_reason if cancelled else "",
                error={**data, "cancelled": True} if cancelled else data,
            )
            if completed.job_role == "primary":
                self._register_terminal_evidence(completed)
            self.broker.close(job_id)

    def _register_terminal_evidence(self, job: Any) -> None:
        """Persist factual JobAttempt evidence without delaying job success."""
        try:
            from server.services.research_graph.branch.job_attempt import (
                persist_terminal_job_evidence,
            )

            detail = self.repository.load_detail(
                job.job_id,
                owner=job.owner,
            )
            if detail is None:
                return
            registered = persist_terminal_job_evidence(
                detail=detail,
                owner=job.owner,
            )
            if registered is not None:
                self.broker.publish(
                    job.job_id,
                    "evidence_registered",
                    registered,
                )
        except Exception:
            _LOGGER.exception(
                "terminal JobAttempt evidence registration failed: %s",
                job.job_id,
            )

    def _handle_worker_loss(self, job_id: str, message: dict[str, Any], *, stage: str) -> None:
        # A terminated/crashed worker does not emit ``task_finished``.  Clear
        # the scheduler's in-memory ownership set here as well, otherwise a
        # cancelled job can permanently consume the owner's concurrency slot
        # even though the replacement worker is idle.
        if stage == "planning":
            self._planning.discard(job_id)
        else:
            self._executing.discard(job_id)
        job = self.repository.load(job_id)
        if job is None or job.status not in {JobStatus.PLANNING, JobStatus.RUNNING}:
            return
        cancelled = job.cancel_requested_at is not None
        completed = self.repository.transition(
            job_id,
            JobStatus.CANCELLED if cancelled else JobStatus.FAILED,
            expected=job.status,
            worker_exitcode=message.get("worker_exitcode"),
            cancel_reason=job.cancel_reason if cancelled else "",
            error={
                "cancelled": cancelled,
                "code": "worker_terminated" if cancelled else "worker_crashed",
                "message": "worker stopped before producing a terminal result",
                "stage": stage,
                "worker_pid": message.get("worker_pid"),
                "worker_exitcode": message.get("worker_exitcode"),
            },
        )
        if completed.job_role == "primary":
            self._register_terminal_evidence(completed)
        self.broker.publish(job_id, "error", completed.error or {})
        self.broker.close(job_id)

    def _enforce_storage_quota(self, owner: str) -> None:
        quota = self.repository.storage_quota(
            owner=owner, default_bytes=default_user_quota_bytes()
        )
        if self.repository.storage_usage(owner=owner) <= quota:
            return
        waiting = self.repository.list(
            owner=owner,
            statuses=(
                JobStatus.SUBMITTED,
                JobStatus.PLANNING,
                JobStatus.AWAITING_CONFIRMATION,
                JobStatus.QUEUED,
            ),
            limit=200,
        )
        for job in waiting:
            self.repository.request_cancel(
                job.job_id,
                owner=owner,
                reason="storage_quota_exceeded",
            )

    def continue_step(self, job_id: str, command: dict[str, Any]) -> bool:
        job = self.repository.load(job_id)
        if job is None or job.status is not JobStatus.PAUSED or not job.step_mode:
            return False
        self.repository.transition(
            job_id,
            JobStatus.RUNNING,
            expected=JobStatus.PAUSED,
        )
        if self.executors.resume_step(job_id, command):
            self.broker.publish(job_id, "status", {"status": "running"})
            return True
        self.repository.transition(
            job_id,
            JobStatus.FAILED,
            expected=JobStatus.RUNNING,
            error={
                "code": "step_worker_unavailable",
                "message": "paused worker is no longer available",
            },
        )
        return False

    def set_draining(self, draining: bool) -> None:
        self._draining = bool(draining)

    def health_snapshot(self) -> dict[str, Any]:
        paused = self.repository.list_for_deployment(
            deployment_id=self.deployment_id,
            statuses=(JobStatus.PAUSED,),
        )
        return {
            "deployment_id": self.deployment_id,
            "draining": self._draining,
            "active_planners": len(self._planning),
            "active_executors": len(self._executing),
            "paused_jobs": [job.job_id for job in paused],
            "planner_workers": self.planners.worker_snapshot(),
            "execution_workers": self.executors.worker_snapshot(),
        }

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
