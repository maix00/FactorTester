"""Collect terminal Job artifacts into their exact Work Package chapter."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
from typing import Any

from tools.cli.commands.research_report_scope import (
    BranchReportScope,
    ensure_authoring,
    persist_descriptor,
)

from .authoring import apply_branch_batch
from .writer import render_branch_authoring_report


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
_SAFE_NODE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_MAX_TABLE_ROWS = 4096
_MAX_TABLE_COLUMNS = 32


def collect_job_report(
    client: Any, *, job_id: str, scope: BranchReportScope,
) -> dict[str, Any]:
    """Download a terminal Job and mount report-ready artifacts once.

    Raw job files remain under the Work Package artifact archive.  The report
    receives only statistical tables and passive images, nested under the
    immutable Graph node that authorized this Job.
    """
    detail = client.get_job(job_id)
    status = _terminal_status(detail)
    binding = _validate_scope(detail, scope)
    execution_node = binding["execution_node"]
    authoring = ensure_authoring(scope, node_id=execution_node)
    parent_id = _chapter_component_id(authoring["bindings"], execution_node)
    if parent_id is None:
        raise ValueError("任务执行节点没有可用的本地报告章节")
    output_root = (
        scope.package_root / "artifacts" / "jobs" / str(job_id)
    )
    output_root.mkdir(parents=True, exist_ok=True)

    mounted: list[dict[str, Any]] = []
    operations: list[dict[str, Any]] = []
    existing_ids = {item["component_id"] for item in authoring["components"]}
    downloaded: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for metadata in client.list_job_artifacts(job_id):
        if str(metadata.get("state") or "active") != "active":
            continue
        name = str(metadata.get("name") or "artifact")
        target = output_root / _download_name(metadata)
        raw = _download(client, job_id, name, target)
        digest = hashlib.sha256(raw).hexdigest()
        downloaded.append({
            "name": name, "path": str(target), "content_hash": digest,
            "size_bytes": len(raw),
        })
        kind = _mount_kind(name, metadata)
        if kind is None:
            skipped.append({"name": name, "reason": "不是统计表格或图片"})
            continue
        try:
            item, mounted_operations = _mount_operations(
                existing_ids=existing_ids, parent_id=parent_id,
                package_root=scope.package_root, job_id=str(job_id), detail=detail,
                metadata=metadata, raw=raw, source_path=target, kind=kind,
            )
        except (TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
            skipped.append({"name": name, "reason": f"无法挂载: {exc}"})
            continue
        mounted.append(item)
        operations.extend(mounted_operations)
    if operations:
        saved = apply_branch_batch(
            package_root=scope.package_root, work_package_id=scope.work_package_id,
            branch_id=scope.branch_id, operations=operations,
        )
        persist_descriptor(scope, saved["descriptor"])
    projection = render_branch_authoring_report(
        package_root=scope.package_root, work_package_id=scope.work_package_id,
        branch_id=scope.branch_id,
    )
    return {
        "job_id": str(job_id), "status": status,
        "execution_node": execution_node,
        "report_file": str(projection["path"]),
        "job_output_dir": str(output_root),
        "downloaded": downloaded, "mounted": mounted, "skipped": skipped,
        "mount_policy": {
            "included": ["statistical_table", "image"],
            "excluded": ["log", "raw", "debug", "archive", "receipt"],
        },
        "git": projection["git"],
    }


def _terminal_status(detail: dict[str, Any]) -> str:
    status = str(
        detail.get("status") or (detail.get("job") or {}).get("status") or ""
    ).lower()
    if status not in {"succeeded", "failed", "cancelled"}:
        raise ValueError(f"Job 尚未结束，不能收集报告生成物: {status or 'unknown'}")
    return status


def _validate_scope(
    detail: dict[str, Any], scope: BranchReportScope,
) -> dict[str, str]:
    binding = detail.get("research_binding") or {}
    if not isinstance(binding, dict):
        raise ValueError("Job 未登记研究工作包绑定，不能挂载到报告")
    expected_package = f"work-package:{scope.work_package_id}"
    if str(binding.get("work_package_ref") or "") != expected_package:
        raise ValueError("Job 不属于指定的研究工作包")
    branch_ref = scope.branch_ref.split(":")
    if len(branch_ref) != 3:
        raise ValueError("本地研究分支身份无效")
    if (
        str(binding.get("instance_id") or "") != branch_ref[1]
        or str(binding.get("branch_id") or "") != scope.branch_id
    ):
        raise ValueError("Job 不属于指定的研究分支")
    node = str(binding.get("execution_node") or "")
    if not _SAFE_NODE.fullmatch(node):
        raise ValueError("历史 Job 未冻结执行节点，不能猜测报告挂载位置")
    return {"execution_node": node}


def _chapter_component_id(bindings: list[dict[str, Any]], node_id: str) -> str | None:
    for item in bindings:
        data = item.get("data") or {}
        if (
            item.get("kind") == "graph_reference"
            and data.get("role") == "report_chapter"
            and data.get("chapter_ref") == f"node:{node_id}"
        ):
            return str(item.get("component_id") or "") or None
    return None


def _download_name(metadata: dict[str, Any]) -> str:
    value = Path(str(metadata.get("file_name") or metadata.get("name") or "artifact")).name
    if not value or value in {".", ".."}:
        value = "artifact"
    if Path(value).suffix:
        return value
    mime = str(metadata.get("content_type") or "").split(";", 1)[0].lower()
    extension = _IMAGE_TYPES.get(mime) or {
        "application/json": ".json", "text/csv": ".csv",
        "text/plain": ".txt",
    }.get(mime, "")
    return value + extension


def _download(client: Any, job_id: str, name: str, target: Path) -> bytes:
    raw = bytes(client.job_artifact(job_id, name).content)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(f".{target.name}.{os.getpid()}.part")
    staging.write_bytes(raw)
    staging.replace(target)
    return raw


def _mount_kind(name: str, metadata: dict[str, Any]) -> str | None:
    mime = str(metadata.get("content_type") or "").split(";", 1)[0].lower()
    if mime in _IMAGE_TYPES:
        return "image"
    return "table" if name in _TABLE_NAMES and mime in _TABLE_TYPES else None


def _mount_operations(
    *, existing_ids: set[str], parent_id: str,
    package_root: Path, job_id: str, detail: dict[str, Any],
    metadata: dict[str, Any], raw: bytes, source_path: Path, kind: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    name = str(metadata.get("name") or "artifact")
    digest = hashlib.sha256(raw).hexdigest()
    component_id = _component_id(job_id, name, digest)
    if component_id in existing_ids:
        return {
            "name": name, "component_id": component_id, "kind": kind,
            "content_hash": digest, "source_path": str(source_path),
        }, []
    operations: list[dict[str, Any]] = []
    if kind == "image":
        asset = _register_image(
            package_root, source_path, raw, metadata, digest,
        )
        operations.append({"op": "asset", "asset": asset})
        content, display_kind = {"asset_ref": asset["asset_ref"]}, "job-artifact-image"
    else:
        content, display_kind = _table_content(raw, metadata), "job-artifact-table"
    operations.append({
        "op": "add", "component_id": component_id, "kind": "special",
        "title": str(metadata.get("description") or name), "parent_id": parent_id,
        "body": f"Job {job_id} · {name}", "content": content,
        "display_kind": display_kind,
        "bindings": _provenance_bindings(job_id, detail, digest),
    })
    existing_ids.add(component_id)
    return {
        "name": name, "component_id": component_id, "kind": kind,
        "content_hash": digest, "source_path": str(source_path),
    }, operations


def _register_image(
    package_root: Path, source_path: Path, raw: bytes, metadata: dict[str, Any],
    digest: str,
) -> dict[str, str]:
    mime = str(metadata.get("content_type") or "").split(";", 1)[0].lower()
    if mime == "image/svg+xml":
        _validate_passive_svg(raw)
    return {
        "asset_ref": f"report-asset:sha256:{digest}", "media_type": mime,
        "filename": source_path.name,
        "caption": str(metadata.get("description") or metadata.get("name") or ""),
        "alt_text": str(metadata.get("description") or "Job image"),
        "local_ref": source_path.relative_to(package_root).as_posix(),
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


def _table_content(raw: bytes, metadata: dict[str, Any]) -> dict[str, Any]:
    mime = str(metadata.get("content_type") or "").split(";", 1)[0].lower()
    if mime == "text/csv":
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
        if not rows:
            raise ValueError("CSV 为空")
        columns, values = rows[0], rows[1:]
    else:
        columns, values = _json_rows(json.loads(raw.decode("utf-8")))
    if not isinstance(columns, list) or not columns:
        raise ValueError("统计表缺少列")
    columns = [str(item)[:256] for item in columns[:_MAX_TABLE_COLUMNS]]
    width = len(columns)
    normalized = []
    for row in values[:_MAX_TABLE_ROWS]:
        if isinstance(row, dict):
            row = [row.get(column, "") for column in columns]
        if not isinstance(row, list):
            raise ValueError("统计表行格式无效")
        normalized.append([str(item)[:2048] for item in row[:width]] + [""] * max(0, width - len(row)))
    return {"columns": columns, "rows": normalized}


def _json_rows(value: Any) -> tuple[list[str], list[list[Any]]]:
    if isinstance(value, dict) and isinstance(value.get("columns"), list) and isinstance(value.get("rows"), list):
        return list(value["columns"]), list(value["rows"])
    if isinstance(value, dict) and isinstance(value.get("rows"), list):
        return _json_rows(value["rows"])
    if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
        columns = list(dict.fromkeys(str(key) for item in value for key in item))
        return columns, [[item.get(column, "") for column in columns] for item in value]
    if isinstance(value, dict):
        return ["key", "value"], [[key, item] for key, item in value.items()]
    if isinstance(value, list):
        return ["value"], [[item] for item in value]
    return ["value"], [[value]]


def _component_id(job_id: str, name: str, digest: str) -> str:
    raw = _SAFE_NAME.sub("-", f"job-{job_id}-{name}").strip("-")
    return (raw[:104] + "-" + digest[:16])[:128]


def _provenance_bindings(job_id: str, detail: dict[str, Any], digest: str) -> list[dict[str, Any]]:
    evidence = ((detail.get("evidence") or {}).get("job_attempt") or {})
    evidence_hash = str(evidence.get("envelope_hash") or "")
    evidence_ref = (
        f"evidence:job_attempt:sha256:{evidence_hash}"
        if re.fullmatch(r"[0-9a-f]{64}", evidence_hash)
        else f"research-job:{job_id}"
    )
    return [{
        "binding_id": binding_id, "kind": kind, "target_ref": target_ref,
        "label": label, "data": {"content_hash": digest},
    } for kind, binding_id, target_ref, label in (
        ("evidence", f"evidence-{job_id}-{digest[:12]}", evidence_ref, "Job 终态证据"),
        ("job", f"job-{job_id}-{digest[:12]}", f"research-job:{job_id}", "Job 来源"),
    )]
