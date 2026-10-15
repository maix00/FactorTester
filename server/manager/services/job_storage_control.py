"""Principal-scoped Job artifact storage control on the Manager data plane."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from server.jobs.artifacts import artifact_root, default_user_quota_bytes
from server.jobs.repository import JobRepository
from server.manager.http.gateway import GatewayResponse


def _response(payload: dict, status: int = 200) -> GatewayResponse:
    return GatewayResponse(status, json.dumps(payload).encode("utf-8"), "application/json")


def _integer(query: dict[str, list[str]], name: str, default: int = 0) -> int:
    return int(query.get(name, [str(default)])[0])


def _remove_files(root: Path, rows: list[dict]) -> dict[str, int]:
    root = root.resolve()
    removed = removed_bytes = failed = 0
    for row in rows:
        if row.get("active_reference"):
            continue
        try:
            path = (root / str(row["relative_path"])).resolve()
            if root not in path.parents:
                failed += 1
                continue
            if not path.is_file():
                continue
            path.unlink()
        except (OSError, RuntimeError, KeyError, ValueError):
            failed += 1
            continue
        removed += 1
        removed_bytes += int(row["size_bytes"])
    return {"deleted_files": removed, "disk_removed_bytes": removed_bytes,
            "failed_files": failed}


def job_storage_response(
    *, path: str, principal: str, method: str,
    repository: JobRepository | None = None,
    root: Path | None = None,
) -> GatewayResponse:
    """Handle only storage inventory and previewed cleanup, without a worker port."""
    parsed = urlparse(path)
    query = parse_qs(parsed.query, keep_blank_values=True)
    owner = str(principal or "").strip()
    if not owner or owner == "__public_jobs__":
        return _response({"success": False, "error": "login required"}, 401)
    if (parsed.path, method) not in {
        ("/api/jobs/storage", "GET"),
        ("/api/jobs/artifacts", "DELETE"),
    }:
        return _response({"success": False, "error": "unsupported storage request"}, 404)
    repo = repository or JobRepository()
    if method == "GET":
        try:
            inventory = repo.storage_inventory(
                owner=owner,
                category=query.get("category", [""])[0],
                limit=_integer(query, "limit", 50),
                offset=_integer(query, "offset"),
            )
        except (TypeError, ValueError):
            return _response({"success": False, "error": "invalid storage page"}, 400)
        breakdown = repo.storage_breakdown(owner=owner)
        usage = int(breakdown["artifact_bytes"])
        quota = repo.storage_quota(
            owner=owner, default_bytes=default_user_quota_bytes(),
        )
        return _response({
            "success": True, "usage_bytes": usage, "quota_bytes": quota,
            "over_quota": usage > quota, **breakdown, **inventory,
            "servers": repo.storage_servers(owner=owner),
            "unattributed_bytes": max(0, usage - inventory["covered_bytes"]),
            "quota_scope": "job_artifacts",
            "excluded_scopes": ["research_reports", "profile_workspaces"],
        })
    cleanup = query.get("cleanup", [""])[0]
    if cleanup not in {"", "eligible", "retry-files"}:
        return _response({"success": False, "error": "invalid cleanup mode"}, 400)
    if not cleanup:
        workspace_id = query.get("workspace_id", [""])[0].strip()
        rows = repo.mark_owner_artifacts_deleted(
            owner=owner, workspace_id=workspace_id,
        )
        files = _remove_files(root or artifact_root(), rows)
        return _response({
            "success": True, "workspace_id": workspace_id,
            "deleted_artifacts": len(rows), **files,
            "usage_bytes": repo.storage_usage(owner=owner),
        })
    if cleanup == "retry-files":
        try:
            rows = repo.deleted_artifact_files(
                owner=owner, after_rowid=_integer(query, "after"),
            )
        except ValueError as exc:
            return _response({"success": False, "error": str(exc)}, 400)
        files = _remove_files(root or artifact_root(), rows)
        return _response({
            "success": True, **files, "scanned": len(rows),
            "next_after": rows[-1]["cleanup_rowid"] if len(rows) == 1000 else None,
        })
    category = query.get("category", [""])[0].strip()
    try:
        rows = repo.mark_cleanup_outputs_deleted(
            owner=owner, category=category,
            expected_count=_integer(query, "expected_count"),
            expected_bytes=_integer(query, "expected_bytes"),
            expected_token=query["expected_token"][0],
        )
    except (KeyError, TypeError, ValueError) as exc:
        return _response({"success": False, "error": str(exc)}, 409)
    files = _remove_files(root or artifact_root(), rows)
    freed = sum(int(row["size_bytes"]) for row in rows)
    return _response({
        "success": True, "category": category or "all_eligible_outputs",
        "deleted_artifacts": len(rows), **files,
        "freed_bytes": freed, "quota_released_bytes": freed,
        "usage_bytes": repo.storage_usage(owner=owner),
    })
