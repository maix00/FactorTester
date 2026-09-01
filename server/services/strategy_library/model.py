"""Validation and source inspection for persistent Strategy entries."""

from __future__ import annotations

VISIBILITIES = frozenset({"private", "shared", "public"})


def normalize_text(value: object, *, field: str, limit: int) -> str:
    result = " ".join(str(value or "").split())
    if len(result) > limit:
        raise ValueError(f"{field} is too long")
    return result


def normalize_visibility(value: object) -> str:
    visibility = str(value or "private").strip().lower()
    if visibility not in VISIBILITIES:
        raise ValueError("strategy visibility must be private, shared, or public")
    return visibility
