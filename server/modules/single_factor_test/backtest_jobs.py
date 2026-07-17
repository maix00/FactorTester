"""HTTP projection and controls for durable research jobs."""

from __future__ import annotations

from copy import deepcopy
import time
import uuid

from flask import Response, jsonify, request, stream_with_context
import orjson

from server.jobs.ipc import DaemonUnavailable
from server.jobs.models import JobRecord
from server.jobs.repository import JobRepository
from server.jobs.states import JobStatus, TERMINAL_STATUSES
from server.modules.single_factor_test import sft_bp
from server.modules.single_factor_test.research_jobs import _daemon_client, _deployment_id
from server.services.session_runtime import require_user


def _urls(job_id: str) -> dict[str, str]:
    root = f"/api/jobs/{job_id}"
    return {
        "status_url": root,
        "stream_url": f"{root}/stream",
        "result_url": f"{root}/result",
        "cancel_url": f"{root}/cancel",
    }


def _statuses() -> set[JobStatus] | None:
    raw = str(request.args.get("status") or "").strip()
    try:
        return {JobStatus(item.strip()) for item in raw.split(",") if item.strip()} or None
    except ValueError as exc:
        raise ValueError("unsupported job status") from exc


def _after_seq() -> int:
    raw = request.args.get("after")
    if raw in (None, ""):
        raw = request.headers.get("Last-Event-ID", "0")
    try:
        return max(0, int(raw or 0))
    except (TypeError, ValueError):
        return 0


def _repository() -> JobRepository:
    return JobRepository()


def _require_job(job_id: str):
    try:
        return _repository().require(job_id, owner=require_user()), None
    except KeyError:
        return None, (jsonify({"success": False, "error": "research job not found"}), 404)


def _sse(event: str, data: dict, *, event_id: int | None = None) -> str:
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append("data: " + orjson.dumps(data).decode())
    return "\n".join(lines) + "\n\n"


@sft_bp.get("/api/jobs")
def list_test_jobs():
    try:
        statuses = _statuses()
        limit = min(200, max(1, int(request.args.get("limit", "20") or 20)))
    except (TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    repository = _repository()
    jobs = repository.list(
        owner=require_user(),
        kind=str(request.args.get("kind") or "").strip(),
        workspace_id=str(request.args.get("workspace_id") or "").strip(),
        run_id=str(request.args.get("run_id") or "").strip(),
        statuses=statuses,
        limit=limit,
    )
    return jsonify({
        "success": True,
        "jobs": [
            {**job.summary(pinned=repository.is_pinned(job.job_id)), **_urls(job.job_id)}
            for job in jobs
        ],
    })


@sft_bp.get("/api/jobs/<job_id>")
def get_test_job(job_id: str):
    job, error = _require_job(job_id)
    if error:
        return error
    repository = _repository()
    return jsonify({
        "success": True,
        **job.summary(pinned=repository.is_pinned(job.job_id)),
        "execution_plan": job.execution_plan,
        "result_summary": job.result_summary,
        "error": job.error,
        **_urls(job.job_id),
    })


@sft_bp.get("/api/jobs/<job_id>/stream")
def stream_test_job(job_id: str):
    job, error = _require_job(job_id)
    if error:
        return error
    owner = require_user()
    after = _after_seq()

    @stream_with_context
    def generate():
        nonlocal after
        while True:
            current = _repository().load(job_id, owner=owner)
            if current is None:
                yield _sse("error", {"error": "research job not found"})
                return
            try:
                snapshot = _daemon_client().events(job_id, after=after, timeout=15.0)
            except DaemonUnavailable:
                yield _sse("reset", {
                    "reason": "daemon_unavailable",
                    "status": current.status.value,
                    "result_summary": current.result_summary,
                    "error": current.error,
                })
                return
            gap = snapshot.get("gap")
            if gap:
                yield _sse("reset", {
                    "reason": "event_gap",
                    "gap": gap,
                    "status": current.status.value,
                    "latest_progress": snapshot.get("latest_progress"),
                    "manifest": snapshot.get("manifest"),
                })
            for event in snapshot.get("events") or []:
                after = max(after, int(event["seq"]))
                yield _sse(event["event"], event["data"], event_id=after)
            if current.status in TERMINAL_STATUSES or snapshot.get("closed"):
                return
            if not snapshot.get("events"):
                yield ": keepalive\n\n"

    return Response(generate(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


@sft_bp.get("/api/jobs/<job_id>/result")
def get_test_job_result(job_id: str):
    job, error = _require_job(job_id)
    if error:
        return error
    base = {"job_id": job.job_id, "kind": job.kind, "run_id": job.run_id, "status": job.status.value}
    if job.status is JobStatus.SUCCEEDED:
        return jsonify({"success": True, **base, "result": job.result_summary})
    if job.status is JobStatus.PAUSED:
        return jsonify({"success": True, **base, "paused": True})
    if job.status in {JobStatus.FAILED, JobStatus.CANCELLED}:
        return jsonify({"success": False, **base, "error": job.error, "cancel_reason": job.cancel_reason})
    return jsonify({"success": False, **base, "error": "job is not complete"}), 202


@sft_bp.post("/api/jobs/<job_id>/cancel")
def cancel_test_job(job_id: str):
    try:
        job = _repository().request_cancel(
            job_id, owner=require_user(), reason="explicit_cancel"
        )
    except KeyError:
        return jsonify({"success": False, "error": "research job not found"}), 404
    try:
        _daemon_client().cancel(job_id)
    except DaemonUnavailable:
        pass
    return jsonify({"success": True, "job_id": job_id, "status": job.status.value})


@sft_bp.post("/api/jobs/<job_id>/approve")
def approve_test_job(job_id: str):
    try:
        job = _repository().approve_plan(job_id, owner=require_user())
    except KeyError:
        return jsonify({"success": False, "error": "research job not found"}), 404
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    try:
        _daemon_client().wake()
    except DaemonUnavailable:
        pass
    return jsonify({"success": True, **job.summary(), **_urls(job.job_id)})


@sft_bp.post("/api/jobs/<job_id>/pin")
def pin_test_job(job_id: str):
    try:
        job = _repository().pin(job_id, owner=require_user())
    except KeyError:
        return jsonify({"success": False, "error": "research job not found"}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, **job.summary(pinned=True)})


@sft_bp.delete("/api/jobs/pin")
def unpin_test_job():
    _repository().unpin(owner=require_user())
    return jsonify({"success": True})


@sft_bp.post("/api/jobs/<job_id>/retry")
def retry_test_job(job_id: str):
    old, error = _require_job(job_id)
    if error:
        return error
    if old.status not in TERMINAL_STATUSES:
        return jsonify({"success": False, "error": "only terminal jobs can be retried"}), 409
    job = _repository().create(JobRecord(
        job_id=uuid.uuid4().hex,
        run_id=old.run_id,
        owner=old.owner,
        workspace_id=old.workspace_id,
        kind=old.kind,
        status=JobStatus.SUBMITTED,
        retry_of=old.job_id,
        attempt=old.attempt + 1,
        step_mode=old.step_mode,
        retention_mode=old.retention_mode,
        deployment_id=_deployment_id(),
        source_revision=old.source_revision,
        runner_path=old.runner_path,
        job_spec=deepcopy(old.job_spec),
        entitlement=old.entitlement,
        created_at=time.time(),
    ))
    try:
        _daemon_client().wake()
    except DaemonUnavailable:
        pass
    return jsonify({"success": True, **job.summary(), **_urls(job.job_id)}), 202
