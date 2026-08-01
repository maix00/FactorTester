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
    return _load_receipt_path(path, sequence)


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


def load_matching_receipt(
    paths: dict[str, Path],
    *,
    sequence: int,
    logical_digest: str,
    payload_hash: str,
) -> dict[str, Any] | None:
    """Find one receipt by its complete idempotency identity.

    A Git checkout may intentionally rewind report HEAD while the durable,
    untracked receipt directory remains.  In that case the same numerical
    generation can describe a different logical submission.  Keep both
    receipts and distinguish them by digest instead of overwriting history.
    """
    legacy = matching_receipt(
        load_receipt(paths, sequence),
        sequence=sequence,
        logical_digest=logical_digest,
        payload_hash=payload_hash,
    )
    if legacy is not None:
        return legacy
    path = _qualified_receipt_path(paths, sequence, logical_digest)
    if not path.exists():
        return None
    return matching_receipt(
        _load_receipt_path(path, sequence),
        sequence=sequence,
        logical_digest=logical_digest,
        payload_hash=payload_hash,
    )


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
        if existing == value:
            return existing
        path = _qualified_receipt_path(
            paths, submission.sequence, submission.logical_digest,
        )
        if path.exists():
            qualified = _load_receipt_path(path, submission.sequence)
            if qualified != value:
                raise ValueError(
                    "report submission receipt conflicts with finalized state"
                )
            return qualified
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


def _qualified_receipt_path(
    paths: dict[str, Path], sequence: int, logical_digest: str,
) -> Path:
    if (
        len(logical_digest) != 64
        or any(character not in "0123456789abcdef" for character in logical_digest)
    ):
        raise ValueError("report submission receipt digest is invalid")
    return paths["submission_receipts"] / f"{sequence}-{logical_digest}.json"


def _load_receipt_path(path: Path, sequence: int) -> dict[str, Any]:
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
