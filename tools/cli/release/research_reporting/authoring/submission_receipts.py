"""Durable idempotency receipts for finalized report submissions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .submission_lease import ReportSubmission
from .tree_store import atomic_write, load_json


def load_receipt(
    paths: dict[str, Path], sequence: int,
) -> dict[str, Any] | None:
    path = _receipt_path(paths, sequence)
    if not path.exists():
        return None
    value = load_json(path, label="报告提交完成回执")
    required = {
        "schema_version", "submission_sequence", "logical_digest",
        "payload_hash", "attempt", "published_generation",
        "published_root_ref", "finalize_result",
    }
    if set(value) != required or value.get("schema_version") != 1:
        raise ValueError("report submission receipt schema is invalid")
    if (
        value["submission_sequence"] != sequence
        or value["published_generation"] != sequence
        or not isinstance(value["attempt"], int)
        or value["attempt"] < 1
        or not isinstance(value["published_root_ref"], str)
        or not value["published_root_ref"]
        or not isinstance(value["finalize_result"], dict)
    ):
        raise ValueError("report submission receipt is invalid")
    return value


def matching_receipt(
    receipt: dict[str, Any] | None,
    *,
    sequence: int,
    logical_digest: str,
    payload_hash: str,
) -> dict[str, Any] | None:
    if receipt is None:
        return None
    if (
        receipt["submission_sequence"] != sequence
        or receipt["logical_digest"] != logical_digest
        or receipt["payload_hash"] != payload_hash
    ):
        return None
    return receipt


def write_receipt(
    paths: dict[str, Path],
    *,
    submission: ReportSubmission,
    head: dict[str, Any],
    finalize_result: dict[str, Any],
) -> dict[str, Any]:
    value = {
        "schema_version": 1,
        "submission_sequence": submission.sequence,
        "logical_digest": submission.logical_digest,
        "payload_hash": submission.payload_hash,
        "attempt": submission.attempt,
        "published_generation": head["generation"],
        "published_root_ref": head["root_ref"],
        "finalize_result": finalize_result,
    }
    json.dumps(value, ensure_ascii=False, sort_keys=True)
    path = _receipt_path(paths, submission.sequence)
    existing = load_receipt(paths, submission.sequence)
    if existing is not None:
        if existing != value:
            raise ValueError("report submission receipt conflicts with finalized state")
        return existing
    atomic_write(
        path,
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode() + b"\n",
    )
    return value


def _receipt_path(paths: dict[str, Path], sequence: int) -> Path:
    if not isinstance(sequence, int) or sequence < 1:
        raise ValueError("report submission receipt sequence is invalid")
    return paths["submission_receipts"] / f"{sequence}.json"
