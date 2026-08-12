"""Identity and concurrency checks for one pending report submission."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReportSubmission:
    sequence: int
    base_generation: int
    logical_digest: str
    attempt: int
    payload_hash: str
    phase: str
    published_generation: int | None = None
    finalize_result: dict[str, Any] | None = None


def matching_pending(
    pending: dict[str, Any] | None,
    submission: ReportSubmission,
) -> dict[str, Any]:
    if pending is None:
        raise ValueError("report submission is no longer pending")
    if (
        pending["submission_sequence"] != submission.sequence
        or pending["base_generation"] != submission.base_generation
        or pending["logical_digest"] != submission.logical_digest
        or pending["attempt"] != submission.attempt
        or pending["last_payload_hash"] != submission.payload_hash
    ):
        raise ValueError(
            "report submission lease was superseded by a newer retry"
        )
    return pending


def compatible_identity(previous: Any, current: Any) -> bool:
    """Allow a missing stable target to be filled in the same batch slot."""
    if isinstance(previous, dict) and isinstance(current, dict):
        for key, value in previous.items():
            if key not in current:
                return False
            if (
                key in {"component_id", "binding_id", "asset_ref"}
                and value in {None, ""}
            ):
                continue
            if not compatible_identity(value, current[key]):
                return False
        return True
    if isinstance(previous, list) and isinstance(current, list):
        return len(previous) == len(current) and all(
            compatible_identity(left, right)
            for left, right in zip(previous, current, strict=True)
        )
    return previous == current
