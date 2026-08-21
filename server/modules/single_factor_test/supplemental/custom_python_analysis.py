"""Persistent custom Python analysis Adapter for terminal Jobs."""

from __future__ import annotations

import hashlib
import os
import re
from typing import Any

from server.jobs.artifacts import artifact_root, resolve_artifact_path
from server.jobs.assurance import canonical_hash
from server.jobs.supplemental.custom_python import run_custom_python, validate_source
from server.jobs.supplemental.registry import SupplementalAdapter, register


KIND = "custom_python_analysis"
SOURCE_PREFIX = "custom-analysis-source--"
RESULT_PREFIX = "custom-analysis-result--"


def _token(value: object) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "")).strip("-")[:64]


def artifact_prefixes(tab_id: str) -> tuple[str, str]:
    token = _token(tab_id)
    return f"{SOURCE_PREFIX}{token}", f"{RESULT_PREFIX}{token}"


def _write_source_snapshot(repository, parent, tab: dict[str, Any]) -> dict[str, Any]:
    source = str(tab["source"])
    validate_source(source)
    source_prefix, _result_prefix = artifact_prefixes(str(tab["tab_id"]))
    name = source_prefix
    target = (
        artifact_root() / parent.job_id / "custom-analyses"
        / str(tab["tab_id"]) / "source.py"
    )
    raw = source.encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.parent / f".{target.name}.{os.getpid()}.tmp"
    try:
        staging.write_bytes(raw)
        staging.replace(target)
    except BaseException:
        staging.unlink(missing_ok=True)
        raise
    content_hash = hashlib.sha256(raw).hexdigest()
    return repository.record_derived_artifact(
        job_id=parent.job_id, name=name,
        relative_path=(
            f"{parent.job_id}/custom-analyses/{tab['tab_id']}/source.py"
        ),
        content_type="text/x-python", content_hash=content_hash,
        size_bytes=len(raw), artifact_role="input",
        artifact_kind="custom_analysis_source", file_name="analysis.py",
        logical_path=f"custom-analyses/{tab['tab_id']}/analysis.py",
        title_zh=f"{tab['title']} · Python 提交快照",
    )


def _input_artifacts(repository, parent) -> list[dict[str, str]]:
    values = []
    for artifact in repository.list_artifacts(
        job_id=parent.job_id, owner=parent.owner,
    ):
        if artifact.get("state") != "active":
            continue
        if str(artifact.get("artifact_role") or "output") != "output":
            continue
        values.append({
            "name": str(artifact["name"]),
            "relative_path": str(artifact["relative_path"]),
            "content_hash": str(artifact["content_hash"]),
            "content_type": str(artifact.get("content_type") or ""),
        })
    return values


def prepare(repository, parent, params: dict[str, Any]) -> dict[str, Any]:
    tab_id = str(params.get("tab_id") or "").strip()
    if not tab_id:
        raise ValueError("custom analysis tab_id is required")
    tab = repository.require_custom_analysis(
        parent_job_id=parent.job_id, owner=parent.owner, tab_id=tab_id,
    )
    active = next((
        job for job in repository.list_supplemental(
            parent_job_id=parent.job_id, owner=parent.owner, limit=200,
        )
        if job.supplemental_kind == KIND
        and str((job.job_spec.get("supplemental_payload") or {}).get("tab_id") or "")
        == tab_id
        and job.status.value in {"submitted", "planning", "queued", "running", "paused"}
    ), None)
    if active is not None:
        active_payload = dict(active.job_spec.get("supplemental_payload") or {})
        return {
            "identity": {"version": 1, "tab_id": tab_id},
            "source_artifact_hash": active.source_artifact_hash,
            "artifact_name": str(active_payload["artifact_name"]),
            "reuse_artifact": False,
            "cache_keys": [],
            "payload": active_payload,
        }
    snapshot = _write_source_snapshot(repository, parent, tab)
    artifacts = _input_artifacts(repository, parent)
    input_hash = canonical_hash({"tab_id": tab_id})
    _source_prefix, result_prefix = artifact_prefixes(tab_id)
    artifact_name = result_prefix
    return {
        "identity": {
            "version": 1, "tab_id": tab_id,
        },
        "reuse_artifact": False,
        "source_artifact_hash": input_hash,
        "artifact_name": artifact_name,
        "cache_keys": [],
        "payload": {
            "tab_id": tab_id, "title": str(tab["title"]),
            "source_artifact_name": str(snapshot["name"]),
            "source_relative_path": str(snapshot["relative_path"]),
            "source_content_hash": str(snapshot["content_hash"]),
            "artifacts": artifacts, "artifact_name": artifact_name,
        },
    }


def execute(payload: dict[str, Any], sink, cancel_event) -> None:
    if cancel_event.is_set():
        sink.emit_error("cancelled", cancelled=True)
        return
    snapshot_path = resolve_artifact_path(
        str(payload["source_relative_path"]),
        expected_hash=str(payload["source_content_hash"]),
    )
    source = snapshot_path.read_text(encoding="utf-8")
    validate_source(source)
    inputs = []
    for artifact in payload.get("artifacts") or ():
        inputs.append({
            "name": str(artifact["name"]),
            "path": resolve_artifact_path(
                str(artifact["relative_path"]),
                expected_hash=str(artifact["content_hash"]),
            ),
            "content_hash": str(artifact["content_hash"]),
            "content_type": str(artifact.get("content_type") or ""),
        })
    sink.emit_progress(1, 3, phase="post_replay", message="已验证分析代码与生成物")
    output = run_custom_python(source, inputs)
    if cancel_event.is_set():
        sink.emit_error("cancelled", cancelled=True)
        return
    sink.emit_progress(2, 3, phase="post_replay", message="已完成自定义分析")
    result = {
        "artifact_version": 1,
        "tab_id": str(payload["tab_id"]),
        "title": str(payload["title"]),
        "source_artifact_name": str(payload["source_artifact_name"]),
        "result": output["result"],
        "logs": output["logs"],
    }
    sink.emit_core_artifact_at(
        str(payload["artifact_name"]), result,
        relative_path=f"custom-analyses/{payload['tab_id']}/result.json",
    )
    sink.emit_progress(3, 3, phase="post_replay", message="已保存自定义分析结果")
    sink.emit_result({
        "success": True,
        "tab_id": str(payload["tab_id"]),
        "title": str(payload["title"]),
        "source_artifact_name": str(payload["source_artifact_name"]),
        "artifact_name": str(payload["artifact_name"]),
    })


register(SupplementalAdapter(
    kind=KIND,
    parent_kinds=frozenset(),
    prepare=prepare,
    execute=execute,
))
