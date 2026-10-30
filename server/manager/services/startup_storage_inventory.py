"""One-shot local quota reconciliation after a Manager comes online."""

from __future__ import annotations

import threading
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

from server.manager.services.profile_storage_inventory import scan_profile_storage
from tools.cli.release.local_profile_contracts import validate_principal_identifier


def apply_deferred_output_cleanups(
    state: Any, *, log: Callable[[str], None] = print, limit: int = 100,
) -> dict[str, int]:
    """Execute a target Manager's queued commands once it can reach authority.

    The saved number is quota credit, not a deletion manifest.  A current
    terminal-output preview must still equal the recorded server snapshot;
    otherwise no file is touched and the credit is refunded for review.
    """
    store = getattr(state, "control_store", None)
    if store is None:
        return {"completed": 0, "needs_review": 0, "failed": 0}
    from server.jobs.repository import JobRepository
    from server.manager.services.job_storage_control import job_storage_response

    repo = JobRepository()
    result = {"completed": 0, "needs_review": 0, "failed": 0}
    for _ in range(limit):
        request = store.claim_deferred_output_cleanup(server_id=state.server_id)
        if request is None:
            break
        owner = str(request["principal"])
        request_id = str(request["request_id"])
        try:
            preview = repo.storage_inventory(owner=owner)["cleanup_preview"]
            snapshot_time = datetime.fromisoformat(
                str(request["snapshot_observed_at"]).replace("Z", "+00:00")
            ).timestamp()
            if (int(preview["artifact_count"]) != request["snapshot_output_count"]
                    or int(preview["bytes"]) != request["snapshot_output_bytes"]
                    or float(preview["max_created_at"]) > snapshot_time):
                store.finish_deferred_output_cleanup(
                    server_id=state.server_id, request_id=request_id,
                    status="needs_review",
                    error="terminal output inventory changed or contains newer files; no files deleted",
                )
                result["needs_review"] += 1
                continue
            query = urlencode({
                "cleanup": "eligible", "expected_count": preview["artifact_count"],
                "expected_bytes": preview["bytes"],
                "expected_token": preview["token"],
            })
            response = job_storage_response(
                path=f"/api/jobs/artifacts?{query}", principal=owner,
                method="DELETE", repository=repo,
            )
            detail = json.loads(response.body)
            if response.status != 200 or not detail.get("success"):
                store.finish_deferred_output_cleanup(
                    server_id=state.server_id, request_id=request_id,
                    status="needs_review",
                    error=str(detail.get("error") or "cleanup preview changed"),
                )
                result["needs_review"] += 1
                continue
            store.finish_deferred_output_cleanup(
                server_id=state.server_id, request_id=request_id,
                status="completed",
                deleted_artifacts=int(detail.get("deleted_artifacts") or 0),
                freed_bytes=int(detail.get("freed_bytes") or 0),
                error=(f"{detail['failed_files']} files need physical removal retry"
                       if detail.get("failed_files") else ""),
            )
            result["completed"] += 1
        except Exception as exc:
            result["failed"] += 1
            log(f"deferred Job output cleanup unavailable: {type(exc).__name__}")
            try:
                store.release_deferred_output_cleanup(
                    server_id=state.server_id, request_id=request_id,
                    error=type(exc).__name__,
                )
            except Exception:
                pass
            break
    return result


def sync_local_storage(state: Any, *, log: Callable[[str], None] = print) -> dict[str, int]:
    """Measure complete local Profile trees and refresh existing Job ledgers.

    A failed scan retains its preceding observation. Nothing is deleted or
    recorded as zero because a scan timed out or a directory was unreadable.
    """
    store = getattr(state, "control_store", None)
    if store is None:
        return {"measured": 0, "failed": 0}
    profile_principals: set[str] = set()
    users = Path(state.data_root) / "users"
    if users.is_dir() and not users.is_symlink():
        for path in users.iterdir():
            if not path.is_dir() or path.is_symlink():
                continue
            try:
                profile_principals.add(
                    validate_principal_identifier(path.name, "principal")
                )
            except ValueError:
                continue
    measured = failed = 0
    for principal in sorted(profile_principals):
        try:
            inventory = scan_profile_storage(state.data_root, principal)
            store.record_profile_usage(
                server_id=state.server_id, principal=principal,
                inventory=inventory,
            )
            measured += 1
        except Exception as exc:
            failed += 1
            log(f"startup Profile inventory failed: {type(exc).__name__}")
    try:
        from server.jobs.repository import JobRepository

        repo = JobRepository()
        if repo.db_path.is_file():
            # Job ownership is a storage label, not an identity directory.
            # This bounded projection avoids recreating or querying retired
            # SQLite account tables during startup.
            job_principals: set[str] = set()
            for value in repo.owner_refs():
                try:
                    job_principals.add(
                        validate_principal_identifier(value, "principal")
                    )
                except ValueError:
                    failed += 1
                    log("startup Job inventory skipped an invalid owner ref")
            for principal in sorted(job_principals):
                try:
                    local = repo._local_storage_breakdown(principal)
                    store.reconcile_server_usage(
                        server_id=state.server_id, principal=principal,
                        artifact_bytes=local["artifact_bytes"],
                        input_bytes=local["input_artifact_bytes"],
                        output_bytes=local["output_artifact_bytes"],
                        artifact_count=local["artifact_count"],
                        input_count=local["input_artifact_count"],
                        output_count=local["output_artifact_count"],
                    )
                except Exception as exc:
                    failed += 1
                    log(f"startup Job inventory failed: {type(exc).__name__}")
    except Exception as exc:
        failed += 1
        log(f"startup Job inventory unavailable: {type(exc).__name__}")
    return {"measured": measured, "failed": failed}


def start_storage_inventory(
    state: Any, *, after: threading.Thread | None = None,
    log: Callable[[str], None] = print,
) -> threading.Thread | None:
    if getattr(state, "control_store", None) is None:
        return None

    def run() -> None:
        try:
            if after is not None:
                after.join(timeout=60)
            cleanup = apply_deferred_output_cleanups(state, log=log)
            if any(cleanup.values()):
                log(f"startup deferred Job cleanup: {cleanup}")
            result = sync_local_storage(state, log=log)
            log(f"startup storage inventory: {result['measured']} profiles, {result['failed']} failures")
        except Exception as exc:
            log(f"startup storage inventory unavailable: {type(exc).__name__}")

    thread = threading.Thread(target=run, name="startup-storage-inventory", daemon=True)
    thread.start()
    return thread
