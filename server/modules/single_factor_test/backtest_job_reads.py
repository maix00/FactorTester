"""Read-only HTTP projections for durable research jobs."""

from __future__ import annotations

import hashlib
import time

from flask import Response, jsonify, request, stream_with_context
import orjson

from server.jobs.artifacts import artifact_root, default_user_quota_bytes
from server.jobs.ipc import DaemonUnavailable
from server.jobs.states import JobStatus, TERMINAL_STATUSES
from server.modules.single_factor_test import sft_bp
from server.modules.single_factor_test.backtest_job_support import (
    job_evidence,
    job_urls,
    repository,
    require_job,
)
from server.modules.single_factor_test.research_jobs import _daemon_client
from server.services.session_runtime import require_user


def _statuses() -> set[JobStatus] | None:
    raw = str(request.args.get("status") or "").strip()
    try:
        return {
            JobStatus(item.strip())
            for item in raw.split(",")
            if item.strip()
        } or None
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
        limit = min(
            200,
            max(1, int(request.args.get("limit", "20") or 20)),
        )
    except (TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    rows = repository().list_with_metadata(
        owner=require_user(),
        kind=str(request.args.get("kind") or "").strip(),
        workspace_id=str(
            request.args.get("workspace_id") or ""
        ).strip(),
        run_id=str(request.args.get("run_id") or "").strip(),
        statuses=statuses,
        limit=limit,
    )
    return jsonify({
        "success": True,
        "jobs": [
            {
                **item["job"].summary(pinned=item["pinned"]),
                "artifact_count": item["artifact_count"],
                **job_urls(item["job"].job_id),
            }
            for item in rows
        ],
    })


@sft_bp.get("/api/jobs/<job_id>")
def get_test_job(job_id: str):
    job, error = require_job(job_id)
    if error:
        return error
    return jsonify({
        "success": True,
        **job.summary(pinned=repository().is_pinned(job.job_id)),
        "execution_plan": job.execution_plan,
        "result_summary": job.result_summary,
        "error": job.error,
        "evidence": job_evidence(job),
        **job_urls(job.job_id),
    })


@sft_bp.get("/api/jobs/<job_id>/stream")
def stream_test_job(job_id: str):
    job, error = require_job(job_id)
    if error:
        return error
    owner = require_user()
    after = _after_seq()

    @stream_with_context
    def generate():
        nonlocal after
        while True:
            current = repository().load(job_id, owner=owner)
            if current is None:
                yield _sse(
                    "error",
                    {"error": "research job not found"},
                )
                return
            try:
                snapshot = _daemon_client().events(
                    job_id,
                    after=after,
                    timeout=2.0,
                )
            except DaemonUnavailable:
                yield _sse("reset", {
                    "reason": "daemon_unavailable",
                    "status": current.status.value,
                    "result_summary": current.result_summary,
                    "error": current.error,
                })
                return
            if not snapshot.get("known", True):
                yield _sse("reset", {
                    "reason": "event_state_unavailable",
                    "status": current.status.value,
                    "latest_progress": None,
                    "manifest": None,
                    "result_summary": current.result_summary,
                    "error": current.error,
                })
                if current.status in TERMINAL_STATUSES or after > 0:
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
                yield _sse(
                    event["event"],
                    event["data"],
                    event_id=after,
                )
            if (
                current.status in TERMINAL_STATUSES
                or snapshot.get("closed")
            ):
                return
            if not snapshot.get("events"):
                yield _sse("heartbeat", {
                    "status": current.status.value,
                    "latest_progress": snapshot.get("latest_progress"),
                    "server_time": time.time(),
                })

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@sft_bp.get("/api/jobs/<job_id>/result")
def get_test_job_result(job_id: str):
    job, error = require_job(job_id)
    if error:
        return error
    base = {
        "job_id": job.job_id,
        "kind": job.kind,
        "run_id": job.run_id,
        "status": job.status.value,
        "evidence": job_evidence(job),
    }
    if job.status is JobStatus.SUCCEEDED:
        return jsonify({
            "success": True,
            **base,
            "result": job.result_summary,
        })
    if job.status is JobStatus.PAUSED:
        return jsonify({"success": True, **base, "paused": True})
    if job.status in {JobStatus.FAILED, JobStatus.CANCELLED}:
        return jsonify({
            "success": False,
            **base,
            "error": job.error,
            "cancel_reason": job.cancel_reason,
        })
    return jsonify({
        "success": False,
        **base,
        "error": "job is not complete",
    }), 202


@sft_bp.get("/api/jobs/storage")
def get_job_storage():
    owner = require_user()
    job_repository = repository()
    usage = job_repository.storage_usage(owner=owner)
    quota = job_repository.storage_quota(
        owner=owner,
        default_bytes=default_user_quota_bytes(),
    )
    return jsonify({
        "success": True,
        "usage_bytes": usage,
        "quota_bytes": quota,
        "over_quota": usage > quota,
    })


@sft_bp.get("/api/jobs/<job_id>/artifacts")
def list_test_job_artifacts(job_id: str):
    job, error = require_job(job_id)
    if error:
        return error
    artifacts = repository().list_artifacts(
        job_id=job.job_id,
        owner=job.owner,
    )
    return jsonify({
        "success": True,
        "job_id": job_id,
        "artifacts": artifacts,
    })


@sft_bp.get("/api/jobs/<job_id>/artifacts/<name>")
def get_test_job_artifact(job_id: str, name: str):
    owner = require_user()
    metadata = repository().load_artifact(
        job_id=job_id,
        name=name,
        owner=owner,
    )
    if metadata is None:
        return jsonify({
            "success": False,
            "error": "artifact not found",
        }), 404
    if metadata["state"] != "active":
        return jsonify({
            "success": False,
            "error": "artifact was deleted",
            "artifact": metadata,
        }), 410
    root = artifact_root()
    path = (root / str(metadata["relative_path"])).resolve()
    if root not in path.parents or not path.is_file():
        return jsonify({
            "success": False,
            "error": "artifact file is unavailable",
        }), 410
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != metadata["content_hash"]:
        return jsonify({
            "success": False,
            "error": "artifact integrity check failed",
        }), 500
    return Response(
        raw,
        content_type=str(metadata["content_type"]),
    )
