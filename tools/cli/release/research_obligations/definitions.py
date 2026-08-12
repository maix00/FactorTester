"""Immutable identity fields for a research obligation."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


IMMUTABLE_DEFINITION_FIELDS = ("title_zh", "epistemic_question")


def validate_definition_candidate(
    existing: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    obligation_id: str,
    source: str,
    ignore_blank_candidate: bool = False,
) -> None:
    """Reject a later candidate that changes an established definition."""
    for field in IMMUTABLE_DEFINITION_FIELDS:
        if field not in candidate:
            continue
        before = _definition_text(existing.get(field), field=field)
        after = _definition_text(candidate.get(field), field=field)
        if ignore_blank_candidate and not after:
            continue
        # Legacy ledgers may not yet carry one of the definition fields.  The
        # first non-empty value establishes the immutable definition; only a
        # later attempt to change or clear that established value conflicts.
        if before and before != after:
            raise ValueError(
                "obligation immutable definition conflict: "
                f"{obligation_id}.{field} from {source}"
            )


def validate_definition_history(
    history: list[dict[str, Any]],
    current_obligations: list[dict[str, Any]],
) -> None:
    """Ensure every persisted snapshot keeps the first known definition."""
    seen: dict[str, dict[str, str]] = {}

    def observe(
        obligation_id: str,
        candidate: Mapping[str, Any],
        source: str,
    ) -> None:
        definition = seen.setdefault(obligation_id, {})
        for field in IMMUTABLE_DEFINITION_FIELDS:
            if field not in candidate:
                continue
            value = _definition_text(candidate.get(field), field=field)
            if not value:
                continue
            previous = definition.get(field)
            if previous is None:
                definition[field] = value
            elif previous != value:
                raise ValueError(
                    "obligation immutable definition conflict: "
                    f"{obligation_id}.{field} from {source}"
                )

    for event in history:
        source = f"ledger event {event.get('event_id') or ''}"
        for key in ("obligation_delta", "server_obligation_delta"):
            for delta in event.get(key) or []:
                if not isinstance(delta, dict):
                    continue
                body = delta.get("obligation")
                if isinstance(body, dict):
                    obligation_id = str(
                        body.get("obligation_id")
                        or delta.get("obligation_id")
                        or ""
                    )
                    if obligation_id:
                        observe(obligation_id, body, source)
        for obligation in event.get("obligations_snapshot") or []:
            if not isinstance(obligation, dict):
                continue
            obligation_id = str(obligation.get("obligation_id") or "")
            if obligation_id:
                observe(obligation_id, obligation, source)
    for obligation in current_obligations:
        obligation_id = str(obligation.get("obligation_id") or "")
        if obligation_id:
            observe(obligation_id, obligation, "current projection")


def normalize_definition_history(ledger: Mapping[str, Any]) -> dict[str, Any]:
    """Backfill missing snapshots and reject changes to known definitions."""
    value = deepcopy(ledger)
    canonical: dict[str, dict[str, str]] = {}

    def normalize(candidate: Any, *, source: str) -> None:
        if not isinstance(candidate, dict):
            return
        obligation_id = str(candidate.get("obligation_id") or "")
        if not obligation_id:
            return
        definition = canonical.setdefault(obligation_id, {})
        for field in IMMUTABLE_DEFINITION_FIELDS:
            if field not in candidate:
                continue
            current = _definition_text(candidate.get(field), field=field)
            established = definition.get(field)
            if established is None:
                if current:
                    definition[field] = current
                continue
            if current and current != established:
                raise ValueError(
                    "obligation immutable definition conflict: "
                    f"{obligation_id}.{field} from {source}"
                )
            if not current:
                candidate[field] = established

    for event in value.get("history") or []:
        source = f"ledger event {event.get('event_id') or ''}"
        for key in ("obligation_delta", "server_obligation_delta"):
            for delta in event.get(key) or []:
                if isinstance(delta, dict):
                    normalize(delta.get("obligation"), source=source)
        for obligation in event.get("obligations_snapshot") or []:
            normalize(obligation, source=source)
    projection = value.get("current_projection") or {}
    for obligation in projection.get("obligations") or []:
        normalize(obligation, source="current projection")
    return value


def _definition_text(value: Any, *, field: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"obligation {field} must be a string")
    return value
