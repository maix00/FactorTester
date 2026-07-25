"""Shared projections for durable research-job HTTP routes."""

from __future__ import annotations

from flask import jsonify, request

from server.jobs.models import JobRecord
from server.jobs.ports import detect_port
from server.jobs.repository import JobRepository
from server.services.research_graph.research_cycle.job_evidence import (
    project_job_attempt_evidence,
)
from server.services.session_runtime import require_user


def job_urls(job_id: str) -> dict[str, str]:
    root = f"/api/jobs/{job_id}"
    return {
        "status_url": root,
        "stream_url": f"{root}/stream",
        "result_url": f"{root}/result",
        "cancel_url": f"{root}/cancel",
    }


def job_research_binding(job: JobRecord) -> dict[str, str]:
    run_spec = job.job_spec.get("run_spec") if isinstance(job.job_spec, dict) else None
    binding = run_spec.get("research_binding") if isinstance(run_spec, dict) else None
    return dict(binding) if isinstance(binding, dict) else {}


def repository() -> JobRepository:
    return JobRepository()


def current_port() -> int:
    return detect_port(request.environ)


def _port_error(job: JobRecord):
    port = current_port()
    # A terminal job is durable history. Its result, configuration, and
    # artifacts remain readable from any sibling listener that shares the
    # authenticated repository, even after the original listener is stopped.
    if job.status.value in {"succeeded", "failed", "cancelled"}:
        return None
    if port and job.service_port and job.service_port != port:
        return jsonify({
            "success": False,
            "error": "job belongs to another FactorTester port",
            "job_port": job.service_port,
        }), 409
    return None


def require_job(job_id: str):
    try:
        job = repository().require(
            job_id,
            owner=require_user(),
        )
        error = _port_error(job)
        return (None, error) if error else (job, None)
    except KeyError:
        return None, (
            jsonify({
                "success": False,
                "error": "research job not found",
            }),
            404,
        )


def require_job_detail(job_id: str):
    detail = repository().load_detail(
        job_id,
        owner=require_user(),
    )
    if detail is not None:
        error = _port_error(detail["job"])
        if error:
            return None, error
        return detail, None
    return None, (
        jsonify({
            "success": False,
            "error": "research job not found",
        }),
        404,
    )


def job_evidence(detail: dict) -> dict:
    job: JobRecord = detail["job"]
    trial_binding = detail["trial_binding"]
    return {
        "trial_binding": trial_binding,
        "terminal_assurance": (
            job.terminal_assurance.to_dict()
            if job.terminal_assurance is not None
            else None
        ),
        "job_attempt": project_job_attempt_evidence(
            job,
            identity_refs=detail["identity_refs"],
            trial_stage=str(
                (trial_binding or {}).get("trial_stage") or ""
            ),
            active_artifacts=detail["active_artifacts"],
        ),
    }
