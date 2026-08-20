"""Manager-owned reads of durable Job artifact metadata."""

from __future__ import annotations

import settings as Settings
from server.jobs.repository import JobRepository
from server.manager.http.job_public_projection import (
    PUBLIC_JOB_PRINCIPAL,
    is_public_job_indexed,
)


class JobArtifactCatalog:
    """Read one server's canonical Job repository without an execution port."""

    def __init__(self, state: object) -> None:
        self.state = state

    def list(self, *, job_id: str, principal: str) -> list[dict[str, object]]:
        target = str(job_id or "").strip()
        viewer = str(principal or "").strip()
        if not target or not viewer:
            raise ValueError("job_id and principal are required")
        repository = JobRepository(Settings.CACHE_DB_PATH)
        public = viewer == PUBLIC_JOB_PRINCIPAL or viewer.startswith(
            f"{PUBLIC_JOB_PRINCIPAL}:"
        )
        if public:
            if not is_public_job_indexed(self.state, target):
                return []
            job = repository.load(target)
            if job is None:
                return []
            owner = job.owner
        else:
            job = repository.load(target, owner=viewer)
            if job is None:
                return []
            owner = viewer
        artifacts = repository.list_artifacts(job_id=target, owner=owner)
        if public:
            artifacts = [
                item for item in artifacts
                if str(item.get("artifact_role") or "output") != "input"
            ]
        return [dict(item) for item in artifacts]


__all__ = ["JobArtifactCatalog"]
