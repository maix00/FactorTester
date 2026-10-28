"""Celery planning dispatcher: submitted JobAttempt -> plan task."""

from __future__ import annotations

import logging

from server import branding
from typing import Any, Callable

from server.jobs.repository.sqlite import JobRepository
from server.jobs.states import JobStatus

from .contract import DispatchMessage

LOGGER = logging.getLogger("factortester.job-planner")


class PlanningDispatcher:
    def __init__(
        self, repository: JobRepository, publisher: Any, *,
        target_online: Callable[[str, int], bool] | None = None,
    ) -> None:
        self.repository = repository
        self.publisher = publisher
        self.target_online = target_online

    def run_once(self, *, limit: int = 10) -> dict[str, int]:
        result = {"claimed": 0, "sent": 0, "failed": 0, "deferred": 0}
        deployments = {_deployment_id()}
        deployments.update(row["deployment_id"] for row in self.repository.list_worker_targets()
                           if row.get("capabilities", {}).get("execution_target"))
        jobs = sorted((job for deployment in deployments
                       for job in self.repository.list_for_deployment(
                           deployment_id=deployment, statuses=(JobStatus.SUBMITTED,), limit=limit)),
                      key=lambda job: (job.created_at, job.job_id))
        for job in jobs[:limit]:
            if job.job_role != "primary":
                continue
            if self.target_online is not None and not self.target_online(
                job.deployment_id, job.service_port,
            ):
                result["deferred"] += 1
                continue
            claimed = self.repository.claim_planning(job.job_id, job.attempt)
            if claimed is None:
                continue
            result["claimed"] += 1
            message = DispatchMessage(
                job_id=job.job_id,
                attempt=job.attempt,
                deployment_id=job.deployment_id,
                run_spec_hash=job.run_spec_hash,
                job_spec_hash=job.job_spec_hash,
                service_port=job.service_port,
            )
            try:
                self.publisher.publish_plan(message)
            except Exception as exc:
                self.repository.reset_planning(job.job_id)
                result["failed"] += 1
                LOGGER.warning("planning publish failed for %s: %s", job.job_id, exc)
            else:
                result["sent"] += 1
        return result


def _deployment_id() -> str:
    return branding.env("DEPLOYMENT_ID", "").strip()
