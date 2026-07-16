"""Async backtest job routes for single-factor group tests."""

from __future__ import annotations

from flask import jsonify, request

from server.modules.single_factor_test import sft_bp
from server.services import test_jobs
from server.services.session_runtime import current_user


def _owner() -> str:
    return str(current_user() or "")


def _job_urls(job_id: str) -> dict[str, str]:
    return {
        "status_url": f"/backtest/jobs/{job_id}",
        "stream_url": f"/backtest/jobs/{job_id}/stream",
        "result_url": f"/backtest/jobs/{job_id}/result",
        "cancel_url": f"/backtest/jobs/{job_id}/cancel",
    }


def _api_job_urls(job_id: str) -> dict[str, str]:
    return {
        "status_url": f"/api/jobs/{job_id}",
        "stream_url": f"/api/jobs/{job_id}/stream",
        "result_url": f"/api/jobs/{job_id}/result",
        "cancel_url": f"/api/jobs/{job_id}/cancel",
    }


def _parse_statuses() -> set[str] | None:
    statuses_raw = str(request.args.get("status") or "").strip()
    return {part.strip() for part in statuses_raw.split(",") if part.strip()} or None


def _job_result_response(job):
    if job.status == "succeeded":
        return jsonify({
            "success": True,
            "job_id": job.job_id,
            "kind": job.kind,
            "run_token": job.run_token,
            "page_uuid": job.page_uuid,
            "status": job.status,
            "result": job.result,
        })
    if job.status in {"failed", "cancelled"}:
        return jsonify({
            "success": False,
            "job_id": job.job_id,
            "kind": job.kind,
            "run_token": job.run_token,
            "page_uuid": job.page_uuid,
            "status": job.status,
            "error": job.error,
        })
    return jsonify({
        "success": False,
        "job_id": job.job_id,
        "kind": job.kind,
        "status": job.status,
        "error": "job is not complete",
    }), 202


def _require_job(job_id: str):
    try:
        return test_jobs.require_job(job_id, _owner()), None
    except KeyError:
        return None, (jsonify({"success": False, "error": "test job not found"}), 404)
    except PermissionError as exc:
        return None, (jsonify({"success": False, "error": str(exc)}), 403)


def _submit_by_kind(kind: str, payload: dict):
    if kind == "backtest":
        from server.modules.single_factor_test.group import start_group_test_job

        return start_group_test_job(payload)
    raise ValueError(f"unsupported job kind: {kind}")


@sft_bp.post("/api/jobs")
def submit_test_job():
    data = request.get_json(silent=True) or {}
    kind = str(data.get("kind") or "").strip()
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else data
    if not kind:
        kind = str(payload.get("kind") or "backtest").strip()
    try:
        job = _submit_by_kind(kind, payload)
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    return jsonify({
        "success": True,
        "job_id": job.job_id,
        "kind": job.kind,
        "run_token": job.run_token,
        "status": job.status,
        **_api_job_urls(job.job_id),
    }), 202


@sft_bp.get("/api/jobs")
def list_test_jobs():
    jobs = test_jobs.list_jobs(
        owner=_owner(),
        kind=str(request.args.get("kind") or "").strip() or None,
        page_uuid=str(request.args.get("page_uuid") or "").strip() or None,
        statuses=_parse_statuses(),
        limit=int(request.args.get("limit", "20") or 20),
    )
    return jsonify({"success": True, "jobs": jobs})


@sft_bp.get("/api/jobs/<job_id>")
def get_test_job(job_id: str):
    job, error = _require_job(job_id)
    if error:
        return error
    return jsonify({"success": True, **job.summary(), **_api_job_urls(job.job_id)})


@sft_bp.get("/api/jobs/<job_id>/stream")
def stream_test_job(job_id: str):
    job, error = _require_job(job_id)
    if error:
        return error
    after_seq = int(request.args.get("after", "0") or 0)
    return test_jobs.stream_response(job, after_seq=after_seq)


@sft_bp.get("/api/jobs/<job_id>/result")
def get_test_job_result(job_id: str):
    job, error = _require_job(job_id)
    if error:
        return error
    return _job_result_response(job)


@sft_bp.post("/api/jobs/<job_id>/cancel")
def cancel_test_job(job_id: str):
    try:
        cancelled = test_jobs.cancel(job_id, _owner())
    except KeyError:
        return jsonify({"success": False, "error": "test job not found"}), 404
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    return jsonify({"success": True, "cancelled": cancelled, "job_id": job_id})


@sft_bp.post("/backtest/jobs")
def submit_backtest_job():
    from server.modules.single_factor_test.group import start_group_test_job

    payload = request.get_json(silent=True) or {}
    try:
        job = start_group_test_job(payload)
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    return jsonify({
        "success": True,
        "job_id": job.job_id,
        "kind": job.kind,
        "run_token": job.run_token,
        "status": job.status,
        **_job_urls(job.job_id),
    }), 202


@sft_bp.get("/backtest/jobs")
def list_backtest_jobs():
    limit = int(request.args.get("limit", "20") or 20)
    jobs = test_jobs.list_jobs(
        owner=_owner(),
        kind="backtest",
        page_uuid=str(request.args.get("page_uuid") or "").strip() or None,
        statuses=_parse_statuses(),
        limit=limit,
    )
    return jsonify({"success": True, "jobs": jobs})


@sft_bp.get("/backtest/jobs/<job_id>")
def get_backtest_job(job_id: str):
    try:
        job = test_jobs.require_job(job_id, _owner())
    except KeyError:
        return jsonify({"success": False, "error": "backtest job not found"}), 404
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    return jsonify({"success": True, **job.summary(), **_job_urls(job.job_id)})


@sft_bp.get("/backtest/jobs/<job_id>/stream")
def stream_backtest_job(job_id: str):
    try:
        job = test_jobs.require_job(job_id, _owner())
    except KeyError:
        return jsonify({"success": False, "error": "backtest job not found"}), 404
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    after_seq = int(request.args.get("after", "0") or 0)
    return test_jobs.stream_response(job, after_seq=after_seq)


@sft_bp.get("/backtest/jobs/<job_id>/result")
def get_backtest_job_result(job_id: str):
    try:
        job = test_jobs.require_job(job_id, _owner())
    except KeyError:
        return jsonify({"success": False, "error": "backtest job not found"}), 404
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    return _job_result_response(job)


@sft_bp.post("/backtest/jobs/<job_id>/cancel")
def cancel_backtest_job(job_id: str):
    try:
        cancelled = test_jobs.cancel(job_id, _owner())
    except KeyError:
        return jsonify({"success": False, "error": "backtest job not found"}), 404
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    return jsonify({"success": True, "cancelled": cancelled, "job_id": job_id})
