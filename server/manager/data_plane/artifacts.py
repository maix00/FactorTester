"""Resolve immutable retained Job artifacts for transfer origins."""

from __future__ import annotations

from pathlib import Path

from server.jobs.repository import JobRepository
from server.manager.transfers.models import TransferRecord


class ArtifactOriginResolver:
    def __init__(self, *, job_database: str | Path, artifact_root: str | Path) -> None:
        self.repository = JobRepository(Path(job_database).expanduser().resolve())
        self.artifact_root = Path(artifact_root).expanduser().resolve()

    def __call__(self, transfer: TransferRecord) -> Path:
        job = self.repository.load(transfer.job_id)
        if job is None:
            raise FileNotFoundError("transfer Job is unavailable")
        if transfer.principal not in {job.owner, "__public_jobs__"}:
            raise PermissionError("transfer principal does not own the Job")
        metadata = self.repository.load_artifact(
            job_id=transfer.job_id,
            name=transfer.artifact_name,
            owner=job.owner,
        )
        if metadata is None or str(metadata.get("state") or "") != "active":
            raise FileNotFoundError("transfer artifact is unavailable")
        if (
            transfer.principal == "__public_jobs__"
            and str(metadata.get("artifact_role") or "output") == "input"
        ):
            raise PermissionError("public access cannot read input artifacts")
        if int(metadata.get("size_bytes") or 0) != transfer.expected_size:
            raise RuntimeError("artifact size metadata changed after authorization")
        if str(metadata.get("content_hash") or "").lower() != (
            transfer.expected_sha256
        ):
            raise RuntimeError("artifact hash metadata changed after authorization")
        relative = Path(str(metadata.get("relative_path") or ""))
        if relative.is_absolute():
            raise FileNotFoundError("artifact path is invalid")
        path = (self.artifact_root / relative).resolve()
        if self.artifact_root not in path.parents or not path.is_file():
            raise FileNotFoundError("artifact file is unavailable")
        return path


__all__ = ["ArtifactOriginResolver"]
