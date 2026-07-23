"""Readable, bounded labels projected from persisted research objects."""

from __future__ import annotations

from typing import Any

from .report_checkpoint import (
    MAX_CARRIER_ITEMS,
    bounded_text,
    safe_hash,
    safe_identifier,
    safe_refs,
)


def obligation_presentations(evidence: dict[str, Any]) -> list[dict[str, str]]:
    """Project readable obligation facts from this exact persisted checkpoint."""
    checkpoint = evidence.get("research_cycle_checkpoint")
    obligations = (
        checkpoint.get("obligations")
        if isinstance(checkpoint, dict)
        else []
    )
    result: list[dict[str, str]] = []
    for item in obligations if isinstance(obligations, list) else []:
        if not isinstance(item, dict):
            continue
        identifier = safe_identifier(item.get("obligation_id"))
        question = bounded_text(item.get("epistemic_question"), 240)
        if identifier and question:
            result.append({
                "obligation_ref": f"obligation:{identifier}",
                "question_summary": question,
            })
    return result[:MAX_CARRIER_ITEMS]


def evidence_presentations(evidence: dict[str, Any]) -> list[dict[str, str]]:
    """Project optional human descriptions without exposing evidence payloads."""
    referenced = set(safe_refs(evidence.get("evidence_refs") or []))
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for envelope in _evidence_envelopes(evidence):
        envelope_hash = safe_hash(envelope.get("envelope_hash"))
        reference = f"evidence:{envelope_hash}" if envelope_hash else ""
        if not reference or reference not in referenced or reference in seen:
            continue
        seen.add(reference)
        result.append({
            "evidence_ref": reference,
            "title": bounded_text(envelope.get("title"), 160),
            "claim_summary": bounded_text(
                envelope.get("claim_summary"),
                240,
            ),
        })
    return result[:MAX_CARRIER_ITEMS]


def _evidence_envelopes(value: Any):
    if isinstance(value, dict):
        if (
            value.get("schema_version") == 2
            and isinstance(value.get("envelope_hash"), str)
            and isinstance(value.get("evidence_kind"), str)
        ):
            yield value
            return
        for child in value.values():
            yield from _evidence_envelopes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _evidence_envelopes(child)
