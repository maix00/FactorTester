"""HTTP lifecycle for generic supplemental JobAttempts."""

from __future__ import annotations

from pathlib import Path
import uuid

from flask import jsonify, request, session

from server.jobs.artifacts import artifact_root
from server.jobs.ipc import DaemonUnavailable
from server.jobs.states import JobStatus
from server.jobs.supplemental import SupplementalRequest, request_supplemental
from server.modules.single_factor_test import sft_bp
from server.modules.single_factor_test.backtest_job_support import repository
from server.modules.single_factor_test.research_jobs import (
    _daemon_client,
    _deployment_id,
)
from server.services.session_runtime import require_user
from tools.data.account_manage import get_account, is_super_admin_account


def _can_view(actor: str, owner: str) -> bool:
    if actor == owner or is_super_admin_account(get_account(actor)):
        return True
    account = get_account(owner) or {}
    return str(account.get("parent_username") or "").strip() == actor


def _parent(parent_job_id: str, *, mutate: bool = False):
    if mutate and session.get("manager_gateway_public_jobs"):
        return None, (jsonify({
            "success": False, "error": "访客模式不能提交补充分析",
        }), 403)
    actor = require_user()
    parent = repository().load(parent_job_id)
    if parent is None or parent.job_role != "primary":
        return None, (jsonify({
            "success": False, "error": "research job not found",
        }), 404)
    if not _can_view(actor, parent.owner):
        return None, (jsonify({
            "success": False, "error": "无权访问该任务",
        }), 403)
    return parent, None


def _supplemental_payload(job) -> dict:
    value = job.job_spec.get("supplemental_payload")
    return dict(value) if isinstance(value, dict) else {}


def _recoverable(job) -> bool:
    if job.supplemental_kind != "custom_python_analysis":
        return True
    name = str(_supplemental_payload(job).get("source_artifact_name") or "")
    if not name:
        return False
    artifact = repository().load_artifact(
        job_id=job.parent_job_id, owner=job.owner, name=name,
    )
    return bool(artifact and artifact.get("state") == "active")


def _summary(job) -> dict:
    value = job.summary()
    payload = _supplemental_payload(job)
    value.update({
        "job_role": job.job_role,
        "parent_job_id": job.parent_job_id,
        "supplemental_kind": job.supplemental_kind,
        "source_artifact_hash": job.source_artifact_hash,
        "status_url": f"/api/jobs/{job.parent_job_id}/supplementals/{job.job_id}",
        "stream_url": f"/api/jobs/{job.job_id}/stream",
        "cancel_url": f"/api/jobs/{job.job_id}/cancel",
        "recoverable": _recoverable(job),
        "target": {
            "kind": job.supplemental_kind,
            "tab_id": str(payload.get("tab_id") or ""),
            "analysis_tab": str(payload.get("analysis_tab") or ""),
            "strategy_id": str(payload.get("strategy_id") or ""),
            "strategy_configuration_id": str(
                payload.get("strategy_configuration_id") or ""
            ),
            "product_path_selection_id": str(
                payload.get("product_path_selection_id") or ""
            ),
            "output_requests": list(payload.get("output_requests") or ()),
        },
    })
    return value


def _can_manage(actor: str, owner: str) -> bool:
    return actor == owner or is_super_admin_account(get_account(actor))


def _analysis_parent(parent_job_id: str):
    parent, error = _parent(parent_job_id, mutate=True)
    if error:
        return None, error
    if not _can_manage(require_user(), parent.owner):
        return None, (jsonify({
            "success": False, "error": "无权修改该任务的自定义分析",
        }), 403)
    return parent, None


@sft_bp.get("/api/jobs/<parent_job_id>/custom-analyses")
def list_job_custom_analyses(parent_job_id: str):
    parent, error = _parent(parent_job_id)
    if error:
        return error
    analyses = repository().list_custom_analyses(
        parent_job_id=parent.job_id, owner=parent.owner,
    )
    if session.get("manager_gateway_public_jobs"):
        analyses = [
            {key: value for key, value in item.items() if key != "source"}
            for item in analyses
        ]
    return jsonify({
        "success": True,
        "analyses": analyses,
    })


@sft_bp.post("/api/jobs/<parent_job_id>/custom-analyses")
def create_job_custom_analysis(parent_job_id: str):
    parent, error = _analysis_parent(parent_job_id)
    if error:
        return error
    data = request.get_json(silent=True) or {}
    title = str(data.get("title") or "自定义分析").strip()
    source = str(data.get("source") or "result = {'artifacts': artifacts.list()}")
    try:
        from server.jobs.supplemental.custom_python import validate_source

        validate_source(source)
        value = repository().create_custom_analysis(
            parent_job_id=parent.job_id, owner=parent.owner,
            title=title, source=source, tab_id=uuid.uuid4().hex,
        )
    except (TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    return jsonify({"success": True, "analysis": value}), 201


@sft_bp.patch("/api/jobs/<parent_job_id>/custom-analyses/<tab_id>")
def update_job_custom_analysis(parent_job_id: str, tab_id: str):
    parent, error = _analysis_parent(parent_job_id)
    if error:
        return error
    data = request.get_json(silent=True) or {}
    try:
        current = repository().require_custom_analysis(
            parent_job_id=parent.job_id, owner=parent.owner, tab_id=tab_id,
        )
        title = str(data.get("title", current["title"]))
        source = str(data.get("source", current["source"]))
        from server.jobs.supplemental.custom_python import validate_source

        validate_source(source)
        value = repository().update_custom_analysis(
            parent_job_id=parent.job_id, owner=parent.owner, tab_id=tab_id,
            title=title, source=source,
        )
    except KeyError:
        return jsonify({"success": False, "error": "custom analysis tab not found"}), 404
    except (TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    return jsonify({"success": True, "analysis": value})


@sft_bp.delete("/api/jobs/<parent_job_id>/custom-analyses/<tab_id>")
def delete_job_custom_analysis(parent_job_id: str, tab_id: str):
    parent, error = _analysis_parent(parent_job_id)
    if error:
        return error
    try:
        deleted = repository().delete_custom_analysis(
            parent_job_id=parent.job_id, owner=parent.owner, tab_id=tab_id,
        )
    except KeyError:
        return jsonify({"success": False, "error": "custom analysis tab not found"}), 404
    from server.modules.single_factor_test.supplemental.custom_python_analysis import (
        artifact_prefixes,
    )

    prefixes = artifact_prefixes(tab_id)
    root = artifact_root()
    removed = 0
    for artifact in repository().list_artifacts(
        job_id=parent.job_id, owner=parent.owner,
    ):
        if str(artifact["name"]) not in prefixes:
            continue
        metadata = repository().mark_artifact_deleted(
            job_id=parent.job_id, owner=parent.owner,
            name=str(artifact["name"]),
        )
        if metadata is None:
            continue
        path = (root / str(metadata["relative_path"])).resolve()
        if root in path.parents and path.is_file():
            path.unlink()
            removed += 1
    return jsonify({
        "success": True, "analysis": deleted, "deleted_files": removed,
    })


def _status_filter() -> set[JobStatus] | None:
    raw = str(request.args.get("status") or "").strip()
    if not raw:
        return None
    try:
        return {JobStatus(item.strip()) for item in raw.split(",") if item.strip()}
    except ValueError as exc:
        raise ValueError("unsupported supplemental job status") from exc


@sft_bp.post("/api/jobs/<parent_job_id>/supplementals")
def create_job_supplemental(parent_job_id: str):
    parent, error = _parent(parent_job_id, mutate=True)
    if error:
        return error
    data = request.get_json(silent=True) or {}
    kind = str(data.get("kind") or "").strip()
    params = data.get("params") or {}
    if not kind or not isinstance(params, dict):
        return jsonify({
            "success": False, "error": "kind and object params are required",
        }), 400
    actor = require_user()
    try:
        result = request_supplemental(
            repository(), parent,
            SupplementalRequest(
                kind=kind,
                params=params,
                requester=actor,
                deployment_id=_deployment_id(),
            ),
        )
        if result["job"] is not None:
            try:
                _daemon_client().wake()
            except DaemonUnavailable:
                pass
    except LookupError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    except (TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    if result["artifact"] is not None:
        return jsonify({
            "success": True, "created": False, "cached": True,
            "artifact": result["artifact"], "job": None,
        })
    return jsonify({
        "success": True, "created": bool(result["created"]), "cached": False,
        "artifact": None, "job": _summary(result["job"]),
    }), 201 if result["created"] else 202


@sft_bp.get("/api/jobs/<parent_job_id>/supplementals")
def list_job_supplementals(parent_job_id: str):
    parent, error = _parent(parent_job_id)
    if error:
        return error
    try:
        limit = min(100, max(1, int(request.args.get("limit", "20"))))
        page = max(1, int(request.args.get("page", "1")))
        statuses = _status_filter()
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    search = str(request.args.get("search") or "").strip()
    repo = repository()
    rows = repo.list_supplemental(
        parent_job_id=parent.job_id, owner=parent.owner, search=search,
        statuses=statuses, limit=limit, offset=(page - 1) * limit,
    )
    total = repo.count_supplemental(
        parent_job_id=parent.job_id, owner=parent.owner, search=search,
        statuses=statuses,
    )
    return jsonify({
        "success": True, "jobs": [_summary(item) for item in rows],
        "page": page, "page_size": limit, "total": total,
        "total_pages": max(1, (total + limit - 1) // limit),
    })


@sft_bp.get("/api/jobs/<parent_job_id>/supplementals/<supplemental_job_id>")
def get_job_supplemental(parent_job_id: str, supplemental_job_id: str):
    parent, error = _parent(parent_job_id)
    if error:
        return error
    child = repository().load(supplemental_job_id, owner=parent.owner)
    if (
        child is None or child.job_role != "supplemental"
        or child.parent_job_id != parent.job_id
    ):
        return jsonify({
            "success": False, "error": "supplemental job not found",
        }), 404
    return jsonify({
        "success": True, "job": _summary(child),
        "result_summary": child.result_summary, "error": child.error,
        "recoverable": _recoverable(child),
    })
