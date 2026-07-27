"""Authenticated, bounded Profile research navigation read-model routes."""

from __future__ import annotations

from flask import Response, current_app, jsonify, request

from server.modules.single_factor_test import sft_bp
from server.services.research_graph.profile_research_projection import (
    ProfileResearchProjection,
    projection_etag,
)
from server.services.session_runtime import require_user
from server.services.research_graph.work_packages import (
    WorkPackageConflictError,
    transition_lifecycle,
)


_projection = ProfileResearchProjection()


def _limit(default: int) -> int:
    raw = request.args.get("limit")
    return default if raw in (None, "") else int(raw)


def _response(payload: dict) -> Response:
    etag = projection_etag(payload)
    if request.if_none_match.contains(etag):
        response = Response(status=304)
        response.set_etag(etag)
        response.headers["Cache-Control"] = "private, no-cache"
        return response
    body = {**payload, "etag": f"sha256:{etag}"}
    response = jsonify({"success": True, **body})
    response.set_etag(etag)
    response.headers["Cache-Control"] = "private, no-cache"
    return response


def _error(exc: Exception):
    if isinstance(exc, KeyError):
        status = 404
    elif isinstance(exc, WorkPackageConflictError):
        status = 409
    else:
        status = 400
    return jsonify({"success": False, "error": str(exc)}), status


def _projection_failure(exc: Exception):
    current_app.logger.exception(
        "profile research projection failed",
        exc_info=exc,
    )
    return jsonify({
        "success": False,
        "error": "研究投影暂时无法读取，请稍后重试。",
        "error_code": "research_projection_failed",
    }), 500


@sft_bp.get("/api/profile-research")
def list_profile_research():
    try:
        payload = _projection.list_research(
            owner=require_user(),
            workspace_ref=str(
                request.args.get("workspace_ref") or ""
            ),
            lifecycle=str(request.args.get("lifecycle") or "active"),
            limit=_limit(20),
            after=str(request.args.get("after") or ""),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return _error(exc)
    except Exception as exc:
        return _projection_failure(exc)
    return _response(payload)


@sft_bp.get("/api/profile-research/<research_ref>")
def get_profile_research(research_ref: str):
    try:
        payload = _projection.get_research(
            owner=require_user(),
            research_ref=research_ref,
        )
    except (KeyError, TypeError, ValueError) as exc:
        return _error(exc)
    except Exception as exc:
        return _projection_failure(exc)
    return _response(payload)


@sft_bp.patch("/api/profile-research/<work_package_ref>/lifecycle")
def change_profile_research_lifecycle(work_package_ref: str):
    data = request.get_json(silent=True) or {}
    owner = require_user()
    try:
        payload = transition_lifecycle(
            owner=owner,
            work_package_ref=work_package_ref,
            target=str(data.get("target") or ""),
            expected_revision=int(data.get("expected_revision") or 0),
            actor=owner,
            reason=str(data.get("reason") or ""),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return _error(exc)
    except Exception as exc:
        return _projection_failure(exc)
    return _response(payload)


@sft_bp.get("/api/profile-research/<research_ref>/timeline")
def list_profile_research_timeline(research_ref: str):
    try:
        payload = _projection.list_timeline(
            owner=require_user(),
            research_ref=research_ref,
            limit=_limit(50),
            after=str(request.args.get("after") or ""),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return _error(exc)
    except Exception as exc:
        return _projection_failure(exc)
    return _response(payload)


@sft_bp.get(
    "/api/profile-research/<work_package_ref>/branches/<branch_id>"
)
def get_profile_research_branch(
    work_package_ref: str,
    branch_id: str,
):
    try:
        payload = _projection.get_work_package_branch(
            owner=require_user(),
            work_package_ref=work_package_ref,
            branch_id=branch_id,
        )
    except (KeyError, TypeError, ValueError) as exc:
        return _error(exc)
    except Exception as exc:
        return _projection_failure(exc)
    return _response(payload)


@sft_bp.get(
    "/api/profile-research/<work_package_ref>/branches/"
    "<branch_id>/timeline"
)
def list_profile_research_branch_timeline(
    work_package_ref: str,
    branch_id: str,
):
    try:
        payload = _projection.list_work_package_timeline(
            owner=require_user(),
            work_package_ref=work_package_ref,
            branch_id=branch_id,
            limit=_limit(50),
            after=str(request.args.get("after") or ""),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return _error(exc)
    except Exception as exc:
        return _projection_failure(exc)
    return _response(payload)


@sft_bp.get(
    "/api/profile-research/<work_package_ref>/branches/<branch_id>/"
    "checkpoints/<trace_id>/report-carrier"
)
def get_profile_research_report_carrier(
    work_package_ref: str,
    branch_id: str,
    trace_id: str,
):
    try:
        payload = _projection.get_report_checkpoint(
            owner=require_user(),
            work_package_ref=work_package_ref,
            branch_id=branch_id,
            trace_id=trace_id,
        )
    except (KeyError, TypeError, ValueError) as exc:
        return _error(exc)
    except Exception as exc:
        return _projection_failure(exc)
    return _response(payload)
