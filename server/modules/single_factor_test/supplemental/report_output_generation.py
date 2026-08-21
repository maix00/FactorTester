"""Queued post-run generation of registered report outputs."""

from __future__ import annotations

from typing import Any

import orjson

from server.jobs.artifacts import load_json_artifact
from server.jobs.assurance import canonical_hash
from server.jobs.report_outputs import (
    OUTPUT_DEFINITIONS,
    build_report_artifacts,
    bundle_reports,
    normalize_output_requests,
    source_artifacts_for,
    validate_output_requests,
)
from server.jobs.supplemental.registry import SupplementalAdapter, register

KIND = "report_output_generation"


def _analysis(parent_kind: str) -> str:
    value = str(parent_kind).lower().replace("-", "_")
    return "ic" if value in {"ic", "ic_test"} else "backtest"


def _active_source(repository, parent, name: str) -> dict[str, Any] | None:
    value = repository.load_artifact(
        job_id=parent.job_id, name=name, owner=parent.owner,
    )
    return value if value and value.get("state") == "active" else None


def prepare(repository, parent, params: dict[str, Any]) -> dict[str, Any]:
    analysis = _analysis(parent.kind)
    requested = validate_output_requests(
        normalize_output_requests(params.get("output_requests")), [analysis],
    )
    requested = [
        name for name in requested
        if OUTPUT_DEFINITIONS.get(name, {}).get("after_run")
    ]
    if not requested:
        raise ValueError(f"output_requests must contain a post-run {analysis} output")

    required = source_artifacts_for(requested)
    sources: dict[str, dict[str, Any]] = {}
    missing = []
    for name in sorted(required - {"result"}):
        metadata = _active_source(repository, parent, name)
        if metadata is None:
            missing.append(name)
        else:
            sources[name] = {
                "relative_path": str(metadata["relative_path"]),
                "content_hash": str(metadata["content_hash"]),
            }
    if missing:
        raise LookupError(
            "所选结果缺少运行时保留的基础生成物：" + ", ".join(missing)
        )

    result_artifact = _active_source(repository, parent, "result")
    result_summary = dict(parent.result_summary or {})
    if result_artifact is not None:
        sources["result"] = {
            "relative_path": str(result_artifact["relative_path"]),
            "content_hash": str(result_artifact["content_hash"]),
        }
    elif "result" in required and not result_summary:
        raise LookupError("所选结果缺少可用的回测结果基础数据")

    source_identity = {
        name: value["content_hash"] for name, value in sources.items()
    }
    if "result" not in sources:
        source_identity["result_summary"] = canonical_hash(result_summary)
    output_states = {}
    for name in requested:
        definition = OUTPUT_DEFINITIONS[name]
        for artifact_name in definition.get("artifacts") or ():
            item = repository.load_artifact(
                job_id=parent.job_id, name=artifact_name, owner=parent.owner,
            )
            output_states[artifact_name] = {
                "state": str(item.get("state") or "") if item else "absent",
                "content_hash": str(item.get("content_hash") or "") if item else "",
                "deleted_at": item.get("deleted_at") if item else None,
            }
    identity = {
        "version": 1,
        "output_requests": requested,
        "sources": source_identity,
        "output_states": output_states,
    }
    bundle_hash = canonical_hash(identity)
    artifact_name = f"report-output-bundle--{bundle_hash[:24]}"
    return {
        "identity": identity,
        "source_artifact_hash": bundle_hash,
        "artifact_name": artifact_name,
        "cache_keys": [f"report-outputs:{bundle_hash}"],
        "reuse_artifact": False,
        "payload": {
            "parent_job_id": parent.job_id,
            "output_requests": requested,
            "sources": sources,
            "result_summary": result_summary,
            "artifact_name": artifact_name,
        },
    }


def execute(payload: dict[str, Any], sink, cancel_event) -> None:
    requested = list(payload.get("output_requests") or ())
    source = {}
    for name, metadata in (payload.get("sources") or {}).items():
        if cancel_event.is_set():
            sink.emit_error("cancelled", cancelled=True)
            return
        source[name] = load_json_artifact(
            str(metadata["relative_path"]), str(metadata["content_hash"]),
        )
    result = source.get("result")
    if not isinstance(result, dict):
        result = dict(payload.get("result_summary") or {})
    source.pop("result", None)
    sink.emit_progress(1, 3, phase="post_replay", message="已加载回测基础生成物")
    reports = build_report_artifacts(
        result, source=source, requested=requested,
        job_id=str(payload.get("parent_job_id") or "") or None,
        progress=lambda completed, total, name: sink.emit_progress(
            completed, max(1, total), phase="post_replay",
            message=f"正在生成 {name}",
        ),
    )
    if not reports:
        raise ValueError("保留的回测数据无法生成所选结果")
    sink.emit_progress(2, 3, phase="post_replay", message="已完成结果计算")
    names = []
    for report in reports:
        sink.emit_bytes_artifact(
            report.name, report.raw, extension=report.extension,
            content_type=report.content_type,
        )
        names.append(report.name)
    for bundle in bundle_reports(reports):
        sink.emit_bytes_artifact(
            bundle.receipt_name, orjson.dumps(bundle.receipt),
            extension="json", content_type="application/json",
        )
        names.append(bundle.receipt_name)
    sentinel = str(payload["artifact_name"])
    sink.emit_core_artifact(sentinel, {
        "schema_version": 1,
        "output_requests": requested,
        "artifacts": names,
    })
    sink.emit_progress(3, 3, phase="post_replay", message="已登记所选结果")
    sink.emit_plan({
        "success": True,
        "artifact_name": sentinel,
        "output_requests": requested,
        "artifacts": names,
    })


register(SupplementalAdapter(
    kind=KIND,
    parent_kinds=frozenset({"backtest", "ic", "ic_test"}),
    prepare=prepare,
    execute=execute,
))
