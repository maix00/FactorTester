"""Mount selected terminal Job artifacts into their exact report chapter."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from tools.cli.commands.research_report_scope import (
    BranchReportScope,
    ensure_authoring,
    persist_descriptor,
)
from tools.cli.release.job_cache import cache_job_artifact, cached_job_artifact

from .authoring import apply_branch_batch
from .job_artifact_mounts import artifact_ref, mount_kind, mount_operations
from .authoring.export import export_branch_report


_SAFE_NODE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")


def collect_job_report(
    client: Any, *, job_id: str, scope: BranchReportScope,
) -> dict[str, Any]:
    """Cache and mount only report-ready tables and passive images once."""
    detail = client.get_job(job_id)
    status = _terminal_status(detail)
    node = _validate_scope(detail, scope)["execution_node"]
    authoring = ensure_authoring(scope, node_id=node)
    parent_id = _chapter_component_id(authoring["bindings"], node)
    if parent_id is None:
        raise ValueError("任务执行节点没有可用的本地报告章节")
    existing_ids = {item["component_id"] for item in authoring["components"]}
    mounted: list[dict[str, Any]] = []
    downloaded: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    operations: list[dict[str, Any]] = []
    for metadata in client.list_job_artifacts(job_id):
        if str(metadata.get("state") or "active") != "active":
            continue
        name = str(metadata.get("name") or "artifact")
        kind = mount_kind(name, metadata)
        if kind is None:
            skipped.append({"name": name, "reason": "不是统计表格或图片"})
            continue
        try:
            raw, cache = _artifact_bytes(client, job_id, name, metadata, scope)
            item, batch = mount_operations(
                existing_ids=existing_ids, parent_id=parent_id, job_id=str(job_id),
                detail=detail, metadata=metadata, raw=raw, kind=kind,
            )
        except (TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
            skipped.append({"name": name, "reason": f"无法挂载: {exc}"})
            continue
        downloaded.append({"name": name, "artifact_ref": artifact_ref(job_id, name), **cache})
        mounted.append(item)
        operations.extend(batch)
    if operations:
        saved = apply_branch_batch(
            package_root=scope.package_root, work_package_id=scope.work_package_id,
            branch_id=scope.branch_id, operations=operations,
        )
        persist_descriptor(scope, saved["descriptor"])
    projection = export_branch_report(
        package_root=scope.package_root, work_package_id=scope.work_package_id,
        branch_id=scope.branch_id,
    )
    return {
        "job_id": str(job_id), "status": status, "execution_node": node,
        "report_file": str(projection["path"]), "downloaded": downloaded,
        "mounted": mounted, "skipped": skipped,
        "mount_policy": {
            "included": ["statistical_table", "image"],
            "excluded": ["log", "raw", "debug", "archive", "receipt"],
        },
        "git": projection["git"],
    }


def _artifact_bytes(
    client: Any, job_id: str, name: str, metadata: dict[str, Any],
    scope: BranchReportScope,
) -> tuple[bytes, dict[str, Any]]:
    expected_hash = str(metadata.get("content_hash") or "")
    cached = cached_job_artifact(job_id=job_id, name=name, expected_hash=expected_hash)
    if cached is not None:
        return bytes(cached.pop("raw")), _cache_summary(cached, hit=True)
    raw = bytes(client.job_artifact(job_id, name).content)
    actual_hash = hashlib.sha256(raw).hexdigest()
    if _HASH.fullmatch(expected_hash) and actual_hash != expected_hash:
        raise ValueError("下载的 Job 生成物哈希不匹配")
    stored = cache_job_artifact(
        job_id=job_id, name=name,
        filename=str(metadata.get("file_name") or name),
        content_type=str(metadata.get("content_type") or ""), raw=raw,
        server_url=str(scope.profile["server"]["base_url"]),
    )
    return raw, _cache_summary(stored, hit=False)


def _cache_summary(value: dict[str, Any], *, hit: bool) -> dict[str, Any]:
    return {
        "content_hash": str(value["content_hash"]),
        "size_bytes": int(value["size_bytes"]), "cache_path": str(value["path"]),
        "cache_hit": hit,
    }


def _terminal_status(detail: dict[str, Any]) -> str:
    status = str(detail.get("status") or (detail.get("job") or {}).get("status") or "").lower()
    if status not in {"succeeded", "failed", "cancelled"}:
        raise ValueError(f"Job 尚未结束，不能收集报告生成物: {status or 'unknown'}")
    return status


def _validate_scope(detail: dict[str, Any], scope: BranchReportScope) -> dict[str, str]:
    binding = detail.get("research_binding") or {}
    if not isinstance(binding, dict):
        raise ValueError("Job 未登记研究工作包绑定，不能挂载到报告")
    expected_package = f"work-package:{scope.work_package_id}"
    if str(binding.get("work_package_ref") or "") != expected_package:
        raise ValueError("Job 不属于指定的研究工作包")
    branch_ref = scope.branch_ref.split(":")
    if len(branch_ref) != 3:
        raise ValueError("本地研究分支身份无效")
    if str(binding.get("instance_id") or "") != branch_ref[1] or str(binding.get("branch_id") or "") != scope.branch_id:
        raise ValueError("Job 不属于指定的研究分支")
    node = str(binding.get("execution_node") or "")
    if not _SAFE_NODE.fullmatch(node):
        raise ValueError("历史 Job 未冻结执行节点，不能猜测报告挂载位置")
    return {"execution_node": node}


def _chapter_component_id(bindings: list[dict[str, Any]], node_id: str) -> str | None:
    for item in bindings:
        data = item.get("data") or {}
        if item.get("kind") == "graph_reference" and data.get("role") == "report_chapter" and data.get("chapter_ref") == f"node:{node_id}":
            return str(item.get("component_id") or "") or None
    return None
