"""Worker entry point for registered supplemental Adapters."""

from __future__ import annotations

from .registry import adapter


def run_supplemental(payload, sink, cancel_event) -> None:
    kind = str(payload.get("supplemental_kind") or "")
    selected = adapter(kind)
    selected.execute(
        dict(payload.get("supplemental_payload") or {}), sink, cancel_event,
    )
