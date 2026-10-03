"""Shared projections for durable research-job HTTP routes."""

from __future__ import annotations

from flask import jsonify, request, session

from server.jobs.models import JobRecord
from server.jobs.ports import detect_port
from server.jobs.repository import JobRepository
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


def job_owner_for_gateway() -> str | None:
    """Resolve the service-side owner for one Manager job request.

    Ordinary Manager gateway requests keep their historical broad lookup
    behavior.  Visitor gateway requests are different: their UUID namespace
    must be applied to every detail/stream lookup so one visitor cannot open
    another visitor's task by guessing a Job id.
    """
    visitor_id = str(session.get("manager_gateway_visitor_id") or "").strip()
    if visitor_id:
        return str(session.get("username") or "").strip() or None
    if session.get("manager_gateway_public_jobs"):
        return None
    return require_user()


def require_job(job_id: str):
    try:
        job = repository().require(
            job_id,
            owner=job_owner_for_gateway(),
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
    # Manager 7998 marks anonymous, bounded public-job requests in the
    # gateway session. This never applies to artifact mutation/downloads.
    visitor_owner = str(
        session.get("username") if session.get("manager_gateway_visitor_id")
        else ""
    ).strip()
    gateway_read = bool(
        session.get("manager_gateway_public_jobs")
        or session.get("manager_gateway")
    )
    try:
        detail = repository().load_detail(
            job_id,
            owner=(
                visitor_owner
                if visitor_owner
                else None if gateway_read else require_user()
            ),
        )
    except Exception as exc:
        # Historical rows can contain optional data written by older clients.
        # Return JSON so the Swift client can keep the list row open and show
        # the actual server-side reason instead of crashing on an HTML 500.
        return None, (
            jsonify({
                "success": False,
                "error": "任务详情读取失败",
                "detail": f"{type(exc).__name__}: {exc}",
            }),
            500,
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
    from server.services.research_evidence_catalog import find_job_evidence

    job: JobRecord = detail["job"]
    trial_binding = detail["trial_binding"]
    canonical = find_job_evidence(owner=job.owner, job_id=job.job_id)
    return {
        "trial_binding": trial_binding,
        "canonical": canonical,
        "terminal_assurance": (
            job.terminal_assurance.to_dict()
            if job.terminal_assurance is not None
            else None
        ),
    }
