"""Deterministic private staging paths shared by Manager and data process."""

from __future__ import annotations

import re
from pathlib import Path

from server.manager.transfers.models import TransferRecord


def destination_path(root: str | Path, transfer: TransferRecord) -> Path:
    """Return the stable promoted path for every Attempt of one upload."""

    base = Path(root).expanduser().resolve()
    target = (
        base
        / _safe_component(transfer.principal)
        / _safe_component(transfer.transfer_id)
        / _safe_component(
            transfer.artifact_name or f"{transfer.transfer_id}.bin"
        )
    ).resolve()
    if base not in target.parents:
        raise ValueError("transfer destination escapes staging root")
    return target


def partial_path(root: str | Path, transfer: TransferRecord) -> Path:
    target = destination_path(root, transfer)
    return target.with_name(f".{target.name}.transfer.tmp")


def resume_offset(root: str | Path, transfer: TransferRecord) -> int:
    partial = partial_path(root, transfer)
    if not partial.is_file():
        return 0
    size = partial.stat().st_size
    if not 0 <= size < transfer.expected_size:
        partial.unlink(missing_ok=True)
        return 0
    return size


def storage_reference(transfer: TransferRecord) -> str:
    return (
        f"submission:{transfer.storage_server_id}:"
        f"{transfer.transfer_id}:{transfer.expected_sha256}"
    )


def _safe_component(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value)).strip(".-")
    if not result:
        raise ValueError("transfer path component is empty")
    return result[:128]


__all__ = [
    "destination_path", "partial_path", "resume_offset", "storage_reference",
]
