"""Mount selected terminal Job artifacts into their exact report chapter."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from tools.cli.commands.research_report_scope import (
    BranchReportScope,
    load_authoring,
    persist_descriptor,
)
from tools.cli.release.job_cache import cache_job_artifact, cached_job_artifact

from .authoring import apply_branch_batch, commit_branch_authoring
from .authoring.tree_presence import ReportTreePresence
from .job_artifact_mounts import (
    artifact_ref,
    mount_kind,
    mount_operations,
    result_container_operation,
)

_SAFE_NODE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")


def collect_job_report(
    client: Any, *, job_id: str, scope: BranchReportScope,
) -> dict[str, Any]:
    """Cache and mount only report-ready tables and passive images once."""
    detail = client.get_job(job_id)
    status = _terminal_status(detail)
    target = _validate_scope(detail, scope)
    authoring = load_authoring(scope)
    parent_id = target["report_parent_id"]
    presence = ReportTreePresence.load(
        package_root=scope.package_root, branch_id=scope.branch_id,
    )
    if not presence.component_exists(parent_id):
        raise ValueError("Job 冻结的报告 parent_id 已不存在")
    new_component_ids: set[str] = set()
    mounted: list[dict[str, Any]] = []
    downloaded: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    result_component_id, operations = result_container_operation(
        component_exists=presence.component_exists,
        parent_id=parent_id,
        job_id=str(job_id),
        detail=detail,
        status=status,
    )
    if operations:
        new_component_ids.add(result_component_id)
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
                component_exists=lambda value: value in new_component_ids
                or presence.component_exists(value),
                parent_id=result_component_id, job_id=str(job_id),
                detail=detail, metadata=metadata, raw=raw, kind=kind,
                cached_filename=str(cache.get("filename") or ""),
            )
        except (TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
            skipped.append({"name": name, "reason": f"无法挂载: {exc}"})
            continue
        downloaded.append({"name": name, "artifact_ref": artifact_ref(job_id, name), **cache})
        mounted.append(item)
        new_component_ids.add(item["component_id"])
        operations.extend(batch)
    if operations:
        saved = apply_branch_batch(
            package_root=scope.package_root, report_workspace_id=scope.report_workspace_id,
            branch_id=scope.branch_id, operations=operations, materialize=False,
        )
        persist_descriptor(scope, saved["descriptor"])
    git = commit_branch_authoring(
        scope.package_root,
        message="Mount report-ready Job artifacts",
    )
    return {
        "job_id": str(job_id), "status": status,
        "report_parent_id": parent_id,
        "result_component_id": result_component_id,
        "report_head": str(authoring["paths"]["head"]), "downloaded": downloaded,
        "mounted": mounted, "skipped": skipped,
        "report_follow_up": {
            "status": "analysis_required",
            "parent_id": result_component_id,
            "message": (
                "测试结果及生成物已添加到研究报告；"
                "请在该测试结果特殊小节下提交结果分析"
            ),
        },
        "mount_policy": {
            "included": ["statistical_table", "image"],
            "excluded": ["log", "raw", "debug", "archive", "receipt"],
        },
        "git": git,
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
        server_url=str(getattr(getattr(client, "session", None), "base_url", "")),
    )
    return raw, _cache_summary(stored, hit=False)


def _cache_summary(value: dict[str, Any], *, hit: bool) -> dict[str, Any]:
    return {
        "content_hash": str(value["content_hash"]),
        "size_bytes": int(value["size_bytes"]), "cache_path": str(value["path"]),
        "filename": Path(str(value["path"])).name, "cache_hit": hit,
    }


def _terminal_status(detail: dict[str, Any]) -> str:
    status = str(detail.get("status") or (detail.get("job") or {}).get("status") or "").lower()
    if status not in {"succeeded", "failed", "cancelled"}:
        raise ValueError(f"Job 尚未结束，不能收集报告生成物: {status or 'unknown'}")
    return status


def _validate_scope(detail: dict[str, Any], scope: BranchReportScope) -> dict[str, str]:
    task_detail = detail.get("task_detail") or {}
    binding = (
        detail.get("report_binding")
        or task_detail.get("report_binding")
        or detail.get("research_binding")
        or {}
    )
    if not isinstance(binding, dict):
        raise TypeError("Job 未登记报告绑定，不能挂载到报告")
    if str(binding.get("report_workspace_id") or "") != scope.report_workspace_id:
        raise ValueError("Job 不属于指定的报告工作区")
    if str(binding.get("branch_id") or "") != scope.branch_id:
        raise ValueError("Job 不属于指定的研究分支")
    parent_id = str(binding.get("report_parent_id") or "")
    if not _SAFE_NODE.fullmatch(parent_id):
        raise ValueError("Job 未冻结有效的报告 parent_id")
    return {"report_parent_id": parent_id}
