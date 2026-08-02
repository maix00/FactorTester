"""Typed report-tree operations for selected Job artifacts."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
from collections.abc import Callable
from typing import Any

from .authoring.inline_links import typed_link_list
from .authoring.special_section_operation import add_special_section_operation
from .job_artifact_tables import table_content


_IMAGE_TYPES = {
    "image/svg+xml": ".svg", "image/png": ".png",
    "image/jpeg": ".jpg", "image/webp": ".webp",
}
_TABLE_TYPES = {"text/csv", "application/json"}
_TABLE_NAMES = {
    "equity_curve_data", "returns_over_time_data", "metrics_over_time_data",
    "fee_detail_csv", "fee_detail_data", "margin_detail_csv",
    "margin_detail_data", "ratio_detail_csv", "ratio_detail_data",
}
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def mount_kind(name: str, metadata: dict[str, Any]) -> str | None:
    mime = _mime(metadata)
    if mime in _IMAGE_TYPES:
        return "image"
    return "table" if name in _TABLE_NAMES and mime in _TABLE_TYPES else None


def mount_operations(
    *, component_exists: Callable[[str], bool], parent_id: str, job_id: str,
    detail: dict[str, Any], metadata: dict[str, Any], raw: bytes, kind: str,
    cached_filename: str = "",
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    name = str(metadata.get("name") or "artifact")
    digest = hashlib.sha256(raw).hexdigest()
    component_id = _component_id(job_id, name, digest)
    if component_exists(component_id):
        return _mounted(name, component_id, kind, digest), []
    if kind == "image":
        asset = _image_asset(job_id, name, raw, metadata, digest)
        operations: list[dict[str, Any]] = [{"op": "asset", "asset": asset}]
        content = {"asset_ref": asset["asset_ref"]}
    else:
        operations = []
        content = table_content(
            raw, _mime(metadata), source=_table_source(
                job_id, name, metadata, digest, cached_filename,
            ),
        )
    bindings = provenance_bindings(job_id, detail, digest)
    operations.append({
        "op": "add", "component_id": component_id, "kind": kind,
        "title": str(metadata.get("description") or name), "parent_id": parent_id,
        "body": _report_body(job_id, name, bindings), "content": content,
        "display_kind": "",
        "bindings": bindings,
    })
    return _mounted(name, component_id, kind, digest), operations


def result_container_operation(
    *, component_exists: Callable[[str], bool], parent_id: str, job_id: str,
    detail: dict[str, Any], status: str,
) -> tuple[str, list[dict[str, Any]]]:
    """Return the one stable, collapsible report container owned by a Job."""
    component_id = result_component_id(job_id)
    if component_exists(component_id):
        return component_id, []
    bindings = result_bindings(job_id, detail)
    return component_id, [add_special_section_operation(
        component_id=component_id,
        title=f"测试结果 · {job_id}",
        parent_id=parent_id,
        body=_result_body(job_id, status, bindings),
        display_kind="test_result",
        bindings=bindings,
    )]


def result_component_id(job_id: str) -> str:
    raw = _SAFE_NAME.sub("-", f"job-{job_id}-result").strip("-")
    return raw[:128]


def artifact_ref(job_id: str, name: str) -> str:
    return f"job-artifact:{job_id}:{name}"


def artifact_url(job_id: str, name: str) -> str:
    return f"factortester-artifact://jobs/{job_id}/{name}"


def _mounted(name: str, component_id: str, kind: str, digest: str) -> dict[str, Any]:
    return {"name": name, "component_id": component_id, "kind": kind, "content_hash": digest}


def _image_asset(job_id: str, name: str, raw: bytes, metadata: dict[str, Any], digest: str) -> dict[str, str]:
    mime = _mime(metadata)
    if mime == "image/svg+xml":
        _validate_passive_svg(raw)
    description = str(metadata.get("description") or metadata.get("name") or "")
    return {
        "asset_ref": artifact_ref(job_id, name), "media_type": mime,
        "filename": _filename(name, metadata), "caption": description,
        "alt_text": str(metadata.get("description") or "Job image"),
        "external_ref": artifact_url(job_id, name), "content_hash": digest,
    }


def _table_source(
    job_id: str, name: str, metadata: dict[str, Any], digest: str,
    cached_filename: str,
) -> dict[str, str]:
    return {
        "job_id": job_id,
        "artifact_ref": artifact_ref(job_id, name),
        "filename": cached_filename or _filename(name, metadata),
        "content_type": _mime(metadata),
        "content_hash": digest,
    }


def _validate_passive_svg(raw: bytes) -> None:
    text = raw.decode("utf-8")
    lowered = text.lower()
    forbidden = ("<script", "<foreignobject", "<!doctype", "<!entity", "javascript:")
    if not lowered.lstrip().startswith("<svg") or any(item in lowered for item in forbidden):
        raise ValueError("SVG 含有主动内容")
    if re.search(r"(?:href|src)\s*=\s*[\"']\s*(?:https?:|file:|javascript:)", lowered):
        raise ValueError("SVG 含有外部引用")
    if re.search(r"\son[a-z]+\s*=", lowered):
        raise ValueError("SVG 含有事件处理器")


def provenance_bindings(job_id: str, detail: dict[str, Any], digest: str) -> list[dict[str, Any]]:
    canonical = ((detail.get("evidence") or {}).get("canonical") or {})
    canonical_ref = str(canonical.get("evidence_ref") or "")
    canonical_title = str(canonical.get("title_zh") or "Job 终态证据")
    if canonical_ref:
        return [{
            "binding_id": f"evidence-{job_id}-{digest[:12]}",
            "kind": "evidence",
            "target_ref": canonical_ref,
            "label": canonical_title,
            "data": {"content_hash": digest},
        }]
    return [{
        "binding_id": f"job-{job_id}-{digest[:12]}",
        "kind": "job",
        "target_ref": f"job:{job_id}",
        "label": "测试任务",
        "data": {"content_hash": digest},
    }]


def result_bindings(
    job_id: str, detail: dict[str, Any],
) -> list[dict[str, Any]]:
    """Bind the result container to the terminal Job and its stable evidence."""
    canonical = ((detail.get("evidence") or {}).get("canonical") or {})
    canonical_ref = str(canonical.get("evidence_ref") or "")
    canonical_title = str(canonical.get("title_zh") or "Job 终态证据")
    if canonical_ref:
        bindings = [{
            "binding_id": f"evidence-{job_id}-result",
            "kind": "evidence",
            "target_ref": canonical_ref,
            "label": canonical_title,
            "data": {},
        }]
    else:
        bindings = [{
            "binding_id": f"job-{job_id}-result",
            "kind": "job",
            "target_ref": f"job:{job_id}",
            "label": "测试任务",
            "data": {},
        }]
    research = (
        detail.get("research_binding")
        or (detail.get("task_detail") or {}).get("research_binding")
        or {}
    )
    trial_hash = str(research.get("trial_plan_hash") or "")
    if re.fullmatch(r"[0-9a-f]{64}", trial_hash):
        bindings.append({
            "binding_id": f"trial-plan-{job_id}-result",
            "kind": "trial_plan",
            "target_ref": f"trial-plan:sha256:{trial_hash}",
            "label": "冻结试验计划",
            "data": {},
        })
    run_spec_hash = str(
        detail.get("run_spec_hash")
        or (detail.get("job") or {}).get("run_spec_hash")
        or ((detail.get("task_detail") or {}).get("job") or {}).get(
            "run_spec_hash"
        )
        or ""
    )
    if re.fullmatch(r"[0-9a-f]{64}", run_spec_hash):
        bindings.append({
            "binding_id": f"run-spec-{job_id}-result",
            "kind": "run_spec",
            "target_ref": f"runspec:sha256:{run_spec_hash}",
            "label": "冻结运行配置",
            "data": {},
        })
    return bindings


def _report_body(
    job_id: str, name: str, bindings: list[dict[str, Any]],
) -> str:
    links = typed_link_list([{
        "kind": str(item["kind"]), "target_ref": str(item["target_ref"]),
        "label": str(item["label"]),
    } for item in bindings])
    return f"测试任务 {job_id} · 生成物 {name}\n\n关联：\n{links}"


def _result_body(
    job_id: str, status: str, bindings: list[dict[str, Any]],
) -> str:
    links = typed_link_list([{
        "kind": str(item["kind"]),
        "target_ref": str(item["target_ref"]),
        "label": str(item["label"]),
    } for item in bindings])
    return (
        f"测试任务 {job_id} 已结束，状态为 `{status}`"
        f"\n\n关联：\n{links}"
    )


def _component_id(job_id: str, name: str, digest: str) -> str:
    raw = _SAFE_NAME.sub("-", f"job-{job_id}-{name}").strip("-")
    return (raw[:104] + "-" + digest[:16])[:128]


def _mime(metadata: dict[str, Any]) -> str:
    return str(metadata.get("content_type") or "").split(";", 1)[0].lower()


def _filename(name: str, metadata: dict[str, Any]) -> str:
    value = Path(str(metadata.get("file_name") or name)).name
    return value if value and value not in {".", ".."} else name + _IMAGE_TYPES.get(_mime(metadata), "")
