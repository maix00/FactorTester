"""Stable query and control routes for durable research jobs."""

from __future__ import annotations

import uuid

from flask import jsonify, request

from server.modules.single_factor_test import sft_bp
from server.services import test_jobs
from server.services.session_runtime import require_user


def _urls(job_id: str) -> dict[str, str]:
    root = f"/api/jobs/{job_id}"
    return {
        "status_url": root,
        "stream_url": f"{root}/stream",
        "result_url": f"{root}/result",
        "cancel_url": f"{root}/cancel",
    }


def _statuses() -> set[str] | None:
    raw = str(request.args.get("status") or "").strip()
    return {item.strip() for item in raw.split(",") if item.strip()} or None


def _after_seq() -> int:
    raw = request.args.get("after")
    if raw in (None, ""):
        raw = request.headers.get("Last-Event-ID", "0")
    try:
        return max(0, int(raw or 0))
    except (TypeError, ValueError):
        return 0


def _require_job(job_id: str):
    try:
        return test_jobs.require_job(job_id, require_user()), None
    except KeyError:
        return None, (jsonify({"success": False, "error": "test job not found"}), 404)
    except PermissionError as exc:
        return None, (jsonify({"success": False, "error": str(exc)}), 403)


def _snapshot(job) -> dict:
    return dict(getattr(job, "request_snapshot", {}) or {})


def _resubmit(old, payload: dict, *, view_uuid: str = ""):
    from server.modules.single_factor_test.research_jobs import _submit_kind

    payload.pop("page_uuid", None)
    payload.pop("view_uuid", None)
    if view_uuid:
        payload["view_uuid"] = view_uuid
        payload["lifecycle_policy"] = "observer_bound"
    elif str(payload.get("lifecycle_policy") or "") == "observer_bound":
        payload["lifecycle_policy"] = "durable"
    payload["run_token"] = f"attempt-{uuid.uuid4().hex}"
    payload["_retry_of"] = old.job_id
    payload["_attempt"] = int(getattr(old, "attempt", 1) or 1) + 1
    return _submit_kind(old.kind, payload)


@sft_bp.get("/api/jobs")
def list_test_jobs():
    jobs = test_jobs.list_jobs(
        owner=require_user(),
        kind=str(request.args.get("kind") or "").strip() or None,
        workspace_id=str(request.args.get("workspace_id") or "").strip() or None,
        run_id=str(request.args.get("run_id") or "").strip() or None,
        statuses=_statuses(),
        limit=min(200, max(1, int(request.args.get("limit", "20") or 20))),
    )
    return jsonify({"success": True, "jobs": jobs})


@sft_bp.get("/api/jobs/<job_id>")
def get_test_job(job_id: str):
    job, error = _require_job(job_id)
    if error:
        return error
    return jsonify({"success": True, **job.summary(), **_urls(job.job_id)})


@sft_bp.get("/api/jobs/<job_id>/stream")
def stream_test_job(job_id: str):
    job, error = _require_job(job_id)
    if error:
        return error
    return test_jobs.stream_response(job, after_seq=_after_seq())


@sft_bp.get("/api/jobs/<job_id>/result")
def get_test_job_result(job_id: str):
    job, error = _require_job(job_id)
    if error:
        return error
    base = {"job_id": job.job_id, "kind": job.kind, "run_id": job.run_id, "status": job.status}
    if job.status == "succeeded":
        return jsonify({"success": True, **base, "result": job.result})
    if job.status == "paused":
        return jsonify({"success": True, **base, "checkpoint": getattr(job, "checkpoint", None)})
    if job.status in {"failed", "cancelled", "expired"}:
        return jsonify({"success": False, **base, "error": job.error})
    return jsonify({"success": False, **base, "error": "job is not complete"}), 202


@sft_bp.get("/api/jobs/<job_id>/artifacts/<name>")
def get_test_job_artifact(job_id: str, name: str):
    try:
        artifact = test_jobs.load_artifact(job_id=job_id, owner=require_user(), name=name)
    except KeyError:
        return jsonify({"success": False, "error": "test job not found"}), 404
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    if artifact is None:
        return jsonify({"success": False, "error": "artifact not found"}), 404
    if artifact["status"] != "active":
        return jsonify({"success": False, **artifact}), 410
    return jsonify({
        "success": True,
        "job_id": job_id,
        "name": name,
        "artifact": artifact["value"],
        "metadata": {key: value for key, value in artifact.items() if key != "value"},
    })


@sft_bp.post("/api/jobs/<job_id>/cancel")
def cancel_test_job(job_id: str):
    try:
        cancelled = test_jobs.cancel(job_id, require_user())
    except KeyError:
        return jsonify({"success": False, "error": "test job not found"}), 404
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    return jsonify({"success": True, "cancelled": cancelled, "job_id": job_id})


@sft_bp.post("/api/jobs/<job_id>/retry")
def retry_test_job(job_id: str):
    old, error = _require_job(job_id)
    if error:
        return error
    payload = _snapshot(old)
    if not payload:
        return jsonify({"success": False, "error": "job has no durable RunSpec to retry"}), 400
    data = request.get_json(silent=True) or {}
    view_uuid = str(data.get("view_uuid") or "").strip()
    if view_uuid:
        from server.services import view_leases

        lease = view_leases.load(view_uuid=view_uuid, owner=require_user())
        if lease is None or lease.get("status") != "active" or lease.get("workspace_id") != old.workspace_id:
            return jsonify({"success": False, "error": "active workspace view lease is required"}), 409
    try:
        job = _resubmit(old, payload, view_uuid=view_uuid)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    return jsonify({
        "success": True, "job_id": job.job_id, "retry_of": old.job_id,
        "kind": job.kind, "run_id": job.run_id, "status": job.status,
        **_urls(job.job_id),
    }), 202


@sft_bp.post("/api/jobs/<job_id>/continue")
def continue_test_job(job_id: str):
    old, error = _require_job(job_id)
    if error:
        return error
    if old.kind != "backtest" or old.status != "paused":
        return jsonify({"success": False, "error": "only paused backtest jobs can continue"}), 409
    data = request.get_json(silent=True) or {}
    action = str(data.get("action") or "continue").strip().lower()
    if action not in {"continue", "until", "end"}:
        return jsonify({"success": False, "error": "action must be continue, until, or end"}), 400
    payload = _snapshot(old)
    if action == "end":
        payload["step_mode"] = False
        payload.pop("step_after_index", None)
        payload.pop("step_until", None)
    else:
        checkpoint = getattr(old, "checkpoint", None) or {}
        payload["step_mode"] = True
        payload["step_after_index"] = int(checkpoint.get("flow_index") or 0)
        if action == "until":
            raw_until = str(data.get("until") or "").strip()
            if not raw_until:
                return jsonify({"success": False, "error": "until is required"}), 400
            payload["step_until"] = raw_until
        else:
            payload.pop("step_until", None)
    try:
        job = _resubmit(old, payload)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    return jsonify({
        "success": True, "job_id": job.job_id, "run_id": job.run_id,
        "retry_of": old.job_id, "status": job.status, **_urls(job.job_id),
    }), 202
