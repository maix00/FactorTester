"""One-shot local quota reconciliation after a Manager comes online."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

from server.manager.services.profile_storage_inventory import scan_profile_storage
from tools.cli.release.local_profile_contracts import validate_principal_identifier


def sync_local_storage(state: Any, *, log: Callable[[str], None] = print) -> dict[str, int]:
    """Measure complete local Profile trees and refresh existing Job ledgers.

    A failed scan retains its preceding observation. Nothing is deleted or
    recorded as zero because a scan timed out or a directory was unreadable.
    """
    store = getattr(state, "control_store", None)
    if store is None:
        return {"measured": 0, "failed": 0}
    accounts = store.load_accounts()
    principals = set()
    for account in accounts:
        candidate = str(account.get("username") or "")
        try:
            principals.add(validate_principal_identifier(candidate, "principal"))
        except ValueError:
            continue
    users = Path(state.data_root) / "users"
    if users.is_dir() and not users.is_symlink():
        for path in users.iterdir():
            if not path.is_dir() or path.is_symlink():
                continue
            try:
                principals.add(validate_principal_identifier(path.name, "principal"))
            except ValueError:
                continue
    measured = failed = 0
    for principal in sorted(principals):
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
            for principal in sorted(principals):
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
            result = sync_local_storage(state, log=log)
            log(f"startup storage inventory: {result['measured']} profiles, {result['failed']} failures")
        except Exception as exc:
            log(f"startup storage inventory unavailable: {type(exc).__name__}")

    thread = threading.Thread(target=run, name="startup-storage-inventory", daemon=True)
    thread.start()
    return thread
