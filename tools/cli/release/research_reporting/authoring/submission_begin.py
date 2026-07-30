"""Reserve, resume, or replay one branch-local report submission."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .submission_lease import ReportSubmission, compatible_identity
from .submission_pending import digest, normalized_object, reconcile_pending, write_pending
from .submission_receipts import load_receipt, matching_receipt
from .tree_paths import report_tree_paths
from .tree_store import load_head, tree_lock


def begin_submission(
    *,
    package_root: Path,
    branch_id: str,
    requested_sequence: int | None,
    logical_identity: dict[str, Any],
    payload: Any,
    sidecars: list[dict[str, Any]] | None = None,
) -> ReportSubmission:
    paths = report_tree_paths(package_root, branch_id)
    identity = normalized_object(logical_identity, "logical_identity")
    identity_hash, payload_hash = digest(identity), digest(payload)
    sidecars = list(sidecars or [])
    with tree_lock(paths):
        head = load_head(paths)
        pending = reconcile_pending(paths, head)
        expected = head["generation"] + 1
        if pending is None:
            replay = _finalized_replay(
                paths, requested_sequence, head["generation"],
                identity_hash, payload_hash,
            )
            if replay is not None:
                return replay
            if requested_sequence is not None and requested_sequence != expected:
                raise ValueError(
                    f"submission_sequence must be {expected} for the next report generation"
                )
            value = _new_pending(
                expected, head["generation"], identity, identity_hash, payload_hash,
                sidecars,
            )
        else:
            value = _retry_pending(
                pending, requested_sequence, identity, identity_hash, payload_hash,
                sidecars,
            )
        write_pending(paths, value)
        return ReportSubmission(
            sequence=value["submission_sequence"],
            base_generation=value["base_generation"],
            logical_digest=value["logical_digest"],
            attempt=value["attempt"],
            payload_hash=value["last_payload_hash"],
            phase=value["phase"],
            published_generation=value["published_generation"],
        )


def _finalized_replay(
    paths: dict[str, Path],
    requested: int | None,
    generation: int,
    identity_hash: str,
    payload_hash: str,
) -> ReportSubmission | None:
    if requested is None or requested != generation:
        return None
    receipt = matching_receipt(
        load_receipt(paths, requested),
        sequence=requested,
        logical_digest=identity_hash,
        payload_hash=payload_hash,
    )
    if receipt is None:
        return None
    return ReportSubmission(
        sequence=requested,
        base_generation=requested - 1,
        logical_digest=identity_hash,
        attempt=receipt["attempt"],
        payload_hash=payload_hash,
        phase="finalized",
        published_generation=receipt["published_generation"],
        finalize_result=receipt["finalize_result"],
    )


def _new_pending(
    sequence: int,
    base: int,
    identity: dict[str, Any],
    identity_hash: str,
    payload_hash: str,
    sidecars: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": 4,
        "submission_sequence": sequence,
        "base_generation": base,
        "logical_identity": identity,
        "logical_digest": identity_hash,
        "attempt": 1,
        "last_payload_hash": payload_hash,
        "diagnostics": [],
        "phase": "reserved",
        "published_generation": None,
        "published_root_ref": "",
        "sidecars": sidecars,
    }


def _retry_pending(
    pending: dict[str, Any],
    requested: int | None,
    identity: dict[str, Any],
    identity_hash: str,
    payload_hash: str,
    sidecars: list[dict[str, Any]],
) -> dict[str, Any]:
    sequence = pending["submission_sequence"]
    if requested is None:
        raise ValueError(
            f"pending report submission requires --submission-sequence {sequence}"
        )
    if requested != sequence:
        raise ValueError(
            f"pending report submission requires submission_sequence {sequence}"
        )
    if pending["phase"] == "published":
        if (
            pending["logical_digest"] != identity_hash
            or pending["last_payload_hash"] != payload_hash
        ):
            raise ValueError(
                f"published submission_sequence {sequence} requires the exact same payload"
            )
    elif not compatible_identity(pending["logical_identity"], identity):
        raise ValueError(
            f"submission_sequence {sequence} belongs to a different logical submission"
        )
    if pending["sidecars"] != sidecars:
        raise ValueError(
            f"submission_sequence {sequence} requires the exact same sidecars"
        )
    return {
        **pending,
        "logical_identity": identity,
        "logical_digest": identity_hash,
        "attempt": pending["attempt"] + 1,
        "last_payload_hash": payload_hash,
        "phase": "published" if pending["phase"] == "published" else "reserved",
    }
