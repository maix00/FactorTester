"""Best-effort synchronization of local-run summaries and explicit uploads."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from typing import Any

from tools.cli.http import HttpSession

from .local_runs import LocalRunStore


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def sync_local_run_outbox(
    store: LocalRunStore,
    session: HttpSession,
    *,
    limit: int = 50,
) -> dict[str, Any]:
    """Flush ready operations; a network failure leaves the outbox durable."""
    operations = store.claim_outbox(limit=limit)
    synced = 0
    failed = 0
    results: list[dict[str, Any]] = []
    for operation in operations:
        operation_id = str(operation.get("operation_id") or "")
        try:
            if operation.get("operation_kind") == "sync_summary":
                response = session.post(
                    "/api/client/local-runs/sync",
                    dict(operation.get("payload") or {}),
                )
            elif operation.get("operation_kind") == "upload_artifact":
                response = _upload_artifact(
                    store, session, dict(operation.get("payload") or {}),
                )
            else:
                raise ValueError("unsupported local-run outbox operation")
        except (KeyError, OSError, ValueError, RuntimeError) as error:
            failed += 1
            store.mark_outbox(operation_id, state="error", error=str(error))
            results.append({
                "operation_id": operation_id,
                "state": "error",
                "error": str(error),
            })
            continue
        store.mark_outbox(operation_id, state="synced")
        synced += 1
        results.append({
            "operation_id": operation_id,
            "state": "synced",
            "response": response,
        })
    return {
        "success": failed == 0,
        "processed": len(operations),
        "synced": synced,
        "failed": failed,
        "results": results,
    }


def _upload_artifact(
    store: LocalRunStore,
    session: HttpSession,
    payload: dict[str, Any],
) -> dict[str, Any]:
    job_id = str(payload.get("local_job_id") or "").strip()
    name = str(payload.get("name") or "").strip()
    record = store.get(job_id)
    if record is None:
        raise ValueError("local run is unavailable")
    item = next(
        (value for value in record.get("artifact_manifest") or ()
         if str(value.get("name") or "") == name),
        None,
    )
    if item is None:
        raise ValueError("local artifact is unavailable")
    raw_path = str(item.get("local_path") or "").strip()
    if not raw_path:
        raise FileNotFoundError("local artifact file is unavailable")
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = store.client_root / candidate
    if candidate.is_symlink():
        raise ValueError("local artifact symlinks are not uploadable")
    source = candidate.resolve()
    if store.client_root not in source.parents or not source.is_file():
        raise FileNotFoundError("local artifact file is unavailable")
    raw = source.read_bytes()
    expected_size = int(payload.get("size_bytes") or 0)
    expected_hash = str(payload.get("content_hash") or "").strip().lower()
    if not _SHA256.fullmatch(expected_hash):
        raise ValueError("local artifact must have a complete SHA-256 hash before upload")
    if expected_hash != str(item.get("content_hash") or "").strip().lower():
        raise ValueError("local artifact upload metadata does not match the catalog")
    digest = hashlib.sha256(raw).hexdigest()
    if len(raw) != expected_size or digest != expected_hash:
        raise ValueError("local artifact changed before upload")
    access_response = session.post(
        "/api/client/local-runs/artifacts/access",
        payload,
    )
    access = access_response.get("access") or {}
    url = str(access.get("url") or "").strip()
    bearer = str(access.get("bearer") or "").strip()
    if not url or not bearer:
        raise RuntimeError("local artifact upload capability is invalid")
    request = Request(
        url,
        data=raw,
        method="PUT",
        headers={
            "Authorization": f"Bearer {bearer}",
            "Content-Type": str(payload.get("content_type") or "application/octet-stream"),
            "Content-Length": str(len(raw)),
        },
    )
    try:
        with urlopen(request, timeout=max(30.0, session.timeout)) as response:
            if not 200 <= int(response.status) < 300:
                raise RuntimeError(f"local artifact upload returned HTTP {response.status}")
    except (HTTPError, URLError, OSError, TimeoutError) as error:
        raise ConnectionError("local artifact data-plane upload failed") from error
    transfer_id = str(access.get("transfer_id") or "").strip()
    if not transfer_id:
        raise RuntimeError("local artifact upload transfer id is missing")
    response = session.post(
        "/api/client/local-runs/artifacts/complete",
        {"local_job_id": job_id, "name": name, "transfer_id": transfer_id},
    )
    store.mark_artifact_uploaded(job_id, name, transfer_id)
    return response


__all__ = ["sync_local_run_outbox"]
