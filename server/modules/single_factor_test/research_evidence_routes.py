"""HTTP API for reusable research Evidence objects."""

from flask import jsonify, request

from server.modules.single_factor_test import sft_bp
from server.services.research_evidence_registry import (
    admit_evidence, admit_evidence_for_graph,
    get_evidence,
    put_evidence,
)
from server.services.session_runtime import require_user


@sft_bp.post("/api/research-evidence")
def create_research_evidence():
    data = request.get_json(silent=True) or {}
    try:
        value = put_evidence(
            owner=require_user(), envelope=data.get("envelope"),
            applicability=data.get("applicability") or {},
        )
    except (TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "evidence": value}), 201


@sft_bp.get("/api/research-evidence/<path:evidence_ref>")
def read_research_evidence(evidence_ref: str):
    try:
        value = get_evidence(owner=require_user(), evidence_ref=evidence_ref)
    except (KeyError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    return jsonify({"success": True, "evidence": value})


@sft_bp.post("/api/research-evidence/<path:evidence_ref>/admissions")
def admit_research_evidence(evidence_ref: str):
    data = request.get_json(silent=True) or {}
    try:
        value = admit_evidence(
            owner=require_user(), evidence_ref=evidence_ref,
            environment_ref=str(data.get("environment_ref") or ""),
            subject_ref=str(data.get("subject_ref") or ""),
            qualification=str(data.get("qualification") or ""),
            note=str(data.get("note") or ""),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "admission": value}), 201


@sft_bp.post("/api/research-evidence/<path:evidence_ref>/graph-admissions")
def admit_research_evidence_for_graph(evidence_ref: str):
    """Derive the target scope from an owned Graph branch on the server."""
    data = request.get_json(silent=True) or {}
    try:
        value = admit_evidence_for_graph(
            owner=require_user(), evidence_ref=evidence_ref,
            instance_id=str(data.get("instance_id") or ""),
            branch_id=str(data.get("branch_id") or ""),
            qualification=str(data.get("qualification") or ""),
            note=str(data.get("note") or ""),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "admission": value}), 201
