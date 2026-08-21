"""Idempotent creation of supplemental JobAttempts in research_jobs."""

from __future__ import annotations

from dataclasses import dataclass
import os
import time
import uuid
from typing import Any

from server.jobs.assurance import canonical_hash
from server.jobs.entitlements import entitlement_for_owner
from server.jobs.models import JobRecord
from server.jobs.states import JobStatus, TERMINAL_STATUSES

from .registry import adapter


@dataclass(frozen=True)
class SupplementalRequest:
    kind: str
    params: dict[str, Any]
    requester: str
    deployment_id: str
    source_revision: str = ""


def request_supplemental(repository, parent, request: SupplementalRequest):
    if parent.job_role != "primary" or parent.status not in TERMINAL_STATUSES:
        raise ValueError("supplemental computation requires a terminal primary Job")
    selected = adapter(request.kind)
    if selected.parent_kinds and parent.kind not in selected.parent_kinds:
        raise ValueError(
            f"{request.kind} is unavailable for parent kind {parent.kind}"
        )
    prepared = selected.prepare(repository, parent, dict(request.params))
    identity_payload = prepared.get("identity")
    if not isinstance(identity_payload, dict):
        raise ValueError("supplemental adapter did not provide an identity")
    source_hash = str(prepared.get("source_artifact_hash") or "").strip()
    if not source_hash:
        raise ValueError("supplemental adapter did not provide a source hash")
    artifact_name = str(prepared.get("artifact_name") or "").strip()
    if not artifact_name:
        raise ValueError("supplemental adapter did not provide an artifact name")
    if prepared.get("reuse_artifact", True):
        existing_artifact = repository.load_artifact(
            job_id=parent.job_id, name=artifact_name, owner=parent.owner,
        )
        if existing_artifact and existing_artifact.get("state") == "active":
            return {"artifact": existing_artifact, "job": None, "created": False}
    identity = canonical_hash(identity_payload)
    run_spec = parent.job_spec.get("run_spec")
    if not isinstance(run_spec, dict):
        raise ValueError("parent Job has no compatible RunSpec")
    payload = {
        "run_spec": run_spec,
        "supplemental_kind": request.kind,
        "supplemental_payload": dict(prepared.get("payload") or {}),
        "supplemental_artifact_name": artifact_name,
        "requester": str(request.requester),
        "parent_job_id": parent.job_id,
    }
    plan = {
        "version": 1,
        "kind": request.kind,
        "parent_job_id": parent.job_id,
        "source_artifact_hash": source_hash,
        "artifact_name": artifact_name,
        "cache_keys": list(prepared.get("cache_keys") or ()),
    }
    job, created = repository.create_or_load_supplemental(JobRecord(
        job_id=uuid.uuid4().hex,
        run_id=parent.run_id,
        owner=parent.owner,
        workspace_id=parent.workspace_id,
        kind=parent.kind,
        status=JobStatus.QUEUED,
        job_role="supplemental",
        parent_job_id=parent.job_id,
        supplemental_kind=request.kind,
        supplemental_identity=identity,
        source_artifact_hash=source_hash,
        retention_mode="summary",
        deployment_id=str(request.deployment_id),
        service_port=0,
        source_revision=str(
            request.source_revision
            or os.environ.get("GTHT_SOURCE_REVISION") or ""
        ),
        runner_path="server.jobs.supplemental.runners:run_supplemental",
        job_spec=payload,
        run_spec_hash=parent.run_spec_hash,
        entitlement=entitlement_for_owner(parent.owner),
        execution_plan=plan,
        created_at=time.time(),
    ))
    return {"artifact": None, "job": job, "created": created}
