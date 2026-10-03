"""HTTP API for reusable research Evidence objects."""

from flask import jsonify, request

from server.modules.single_factor_test import sft_bp
from server.services.research_evidence_registry import (
    admit_evidence,
    get_evidence,
)
from server.services.research_evidence_catalog import (
    change_evidence_status,
    attach_tag,
    capture_job_source,
    create_evidence,
    create_source_fragment,
    create_tag,
    detach_tag,
    list_facets,
    list_source_fragments,
    list_tags,
    propose_tag,
    put_source_capture,
    retire_tag,
    search_evidence,
    update_tag,
)
from server.services.session_runtime import require_user


@sft_bp.post("/api/research-evidence")
def create_research_evidence():
    require_user()
    return jsonify({
        "success": False,
        "error": (
            "source-wide Evidence writes are retired; capture a source, "
            "select at least one fragment, then create a composition"
        ),
    }), 410


@sft_bp.post("/api/research-evidence/sources")
def create_research_evidence_source():
    data = request.get_json(silent=True) or {}
    try:
        value = put_source_capture(
            owner=require_user(),
            source_kind=data.get("source_kind"),
            identity=data.get("identity"),
            content_hash=data.get("content_hash"),
            audit=data.get("audit") or {},
            captured_at=data.get("captured_at"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "source": value}), 201


@sft_bp.post("/api/research-evidence/sources/job")
def create_job_evidence_source():
    data = request.get_json(silent=True) or {}
    try:
        value = capture_job_source(
            owner=require_user(), job_id=str(data.get("job_id") or ""),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "source": value}), 201


@sft_bp.post("/api/research-evidence/sources/<path:source_ref>/fragments")
def create_research_evidence_fragment(source_ref: str):
    data = request.get_json(silent=True) or {}
    try:
        value = create_source_fragment(
            owner=require_user(),
            source_ref=source_ref,
            selector=data.get("selector"),
            fragment_hash=data.get("fragment_hash"),
            title_zh=data.get("title_zh"),
            summary_zh=data.get("summary_zh"),
            preview=data.get("preview") or {},
            created_at=data.get("created_at"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "fragment": value}), 201


@sft_bp.get("/api/research-evidence/sources/<path:source_ref>/fragments")
def read_research_evidence_fragments(source_ref: str):
    try:
        value = list_source_fragments(
            owner=require_user(), source_ref=source_ref,
        )
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    return jsonify({"success": True, "fragments": value})


@sft_bp.post("/api/research-evidence/compositions")
def create_fragment_bound_research_evidence():
    data = request.get_json(silent=True) or {}
    try:
        value = create_evidence(
            owner=require_user(),
            evidence_kind=data.get("evidence_kind"),
            fragment_refs=data.get("fragment_refs"),
            title_zh=data.get("title_zh"),
            description_zh=data.get("description_zh"),
            claim_summary=data.get("claim_summary"),
            applicability=data.get("applicability") or {},
            identity_refs=data.get("identity_refs") or {},
            limitations=data.get("limitations") or [],
            conflicts=data.get("conflicts") or [],
        )
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "evidence": value}), 201


@sft_bp.get("/api/research-evidence/facets")
def read_research_evidence_facets():
    return jsonify({
        "success": True,
        "facets": list_facets(owner=require_user()),
    })


@sft_bp.get("/api/research-evidence/search")
def search_research_evidence():
    try:
        value = search_evidence(
            owner=require_user(),
            product_refs=request.args.getlist("product_ref"),
            factor_refs=request.args.getlist("factor_ref"),
            sample_refs=request.args.getlist("sample_ref"),
            time_window=_time_window(),
            evidence_kinds=request.args.getlist("evidence_kind"),
            source_kinds=request.args.getlist("source_kind"),
            tag_refs=request.args.getlist("tag_ref"),
            text=str(request.args.get("text") or ""),
            limit=int(request.args.get("limit") or 20),
            include_excluded=request.args.get("include_excluded") == "1",
        )
    except (TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "result": value})


@sft_bp.get("/api/research-evidence/tags")
def read_research_evidence_tags():
    return jsonify({
        "success": True,
        "tags": list_tags(
            owner=require_user(),
            include_retired=request.args.get("include_retired") == "1",
        ),
    })


@sft_bp.post("/api/research-evidence/tags/proposals")
def propose_research_evidence_tag():
    data = request.get_json(silent=True) or {}
    try:
        value = propose_tag(
            owner=require_user(),
            title_zh=data.get("title_zh"),
            description_zh=data.get("description_zh"),
            created_by_profile_ref=data.get("created_by_profile_ref"),
            distinct_reason=str(data.get("distinct_reason") or ""),
        )
    except (TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "proposal": value}), 201


@sft_bp.post("/api/research-evidence/tags")
def create_research_evidence_tag():
    data = request.get_json(silent=True) or {}
    try:
        value = create_tag(
            owner=require_user(),
            proposal_token=str(data.get("proposal_token") or ""),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "tag": value}), 201


@sft_bp.patch("/api/research-evidence/tags/<path:tag_ref>")
def update_research_evidence_tag(tag_ref: str):
    data = request.get_json(silent=True) or {}
    try:
        value = update_tag(
            owner=require_user(),
            tag_ref=tag_ref,
            title_zh=data.get("title_zh"),
            description_zh=data.get("description_zh"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "tag": value})


@sft_bp.post("/api/research-evidence/tags/<path:tag_ref>/retire")
def retire_research_evidence_tag(tag_ref: str):
    try:
        value = retire_tag(owner=require_user(), tag_ref=tag_ref)
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "tag": value})


@sft_bp.post("/api/research-evidence/<path:evidence_ref>/tags")
def attach_research_evidence_tag(evidence_ref: str):
    data = request.get_json(silent=True) or {}
    try:
        value = attach_tag(
            owner=require_user(),
            evidence_ref=evidence_ref,
            tag_ref=str(data.get("tag_ref") or ""),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "attachment": value}), 201


@sft_bp.delete("/api/research-evidence/<path:evidence_ref>/tags/<path:tag_ref>")
def detach_research_evidence_tag(evidence_ref: str, tag_ref: str):
    try:
        value = detach_tag(
            owner=require_user(), evidence_ref=evidence_ref, tag_ref=tag_ref,
        )
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "attachment": value})


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


@sft_bp.post("/api/research-evidence/<path:evidence_ref>/status")
def change_research_evidence_status(evidence_ref: str):
    data = request.get_json(silent=True) or {}
    try:
        owner = require_user()
        value = change_evidence_status(
            owner=owner, evidence_ref=evidence_ref,
            action=str(data.get("action") or ""),
            reason_zh=str(data.get("reason_zh") or ""),
            profile_ref=owner,
            operation_id=str(data.get("operation_id") or ""),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "lifecycle": value})


def _time_window():
    start = str(request.args.get("time_start") or "")
    end = str(request.args.get("time_end") or "")
    if not start and not end:
        return None
    if not start or not end:
        raise ValueError("time_start and time_end must be provided together")
    return {"start": start, "end": end}
