"""Stable identities for objects carried by the Manager data plane."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TransferObjectKind(StrEnum):
    JOB_ARTIFACT = "job_artifact"
    JOB_SUBMISSION = "job_submission"
    LOCAL_RUN_ARTIFACT = "local_run_artifact"
    RESEARCH_ASSET = "research_asset"
    RESEARCH_ATTACHMENT = "research_attachment"
    RESEARCH_LOCAL_RESOURCE = "research_local_resource"
    EVIDENCE_FILE = "evidence_file"
    FACTOR_SOURCE = "factor_source"
    STRATEGY_REVISION = "strategy_revision"
    PROFILE_WORKSPACE = "profile_workspace"
    CLIENT_RELEASE = "client_release"


@dataclass(frozen=True, slots=True)
class ObjectReference:
    """Immutable metadata needed to authorize one object transfer."""

    kind: TransferObjectKind | str
    object_id: str
    storage_server_id: str
    expected_size: int
    expected_sha256: str
    filename: str = ""
    content_type: str = "application/octet-stream"

    def normalized(self) -> "ObjectReference":
        kind = TransferObjectKind(self.kind)
        object_id = str(self.object_id or "").strip()
        storage_server_id = str(self.storage_server_id or "").strip()
        if not object_id:
            raise ValueError("transfer object id is required")
        if not storage_server_id:
            raise ValueError("transfer object storage server is required")
        size = int(self.expected_size)
        if size < 0:
            raise ValueError("transfer object size must not be negative")
        digest = str(self.expected_sha256 or "").strip().lower()
        if len(digest) != 64 or any(
            char not in "0123456789abcdef" for char in digest
        ):
            raise ValueError("transfer object SHA-256 must be complete")
        return ObjectReference(
            kind=kind,
            object_id=object_id,
            storage_server_id=storage_server_id,
            expected_size=size,
            expected_sha256=digest,
            filename=str(self.filename or "").strip(),
            content_type=str(self.content_type or "application/octet-stream").strip()
            or "application/octet-stream",
        )


def legacy_object_kind(job_id: str, artifact_name: str) -> TransferObjectKind:
    """Return the old Job mapping for callers that have no object fields."""

    del job_id
    return (
        TransferObjectKind.JOB_SUBMISSION
        if str(artifact_name or "").strip().startswith("submission:")
        else TransferObjectKind.JOB_ARTIFACT
    )


__all__ = ["ObjectReference", "TransferObjectKind", "legacy_object_kind"]
