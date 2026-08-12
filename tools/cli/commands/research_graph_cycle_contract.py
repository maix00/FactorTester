"""Shared CLI boundary for one Research Cycle transport envelope."""

from __future__ import annotations

from typing import Any

import click


def validate_research_cycle_envelope(value: dict[str, Any]) -> None:
    """Reject a malformed wire envelope before it enters local state."""
    if value.get("schema_version") != 1:
        raise click.ClickException(
            "research_cycle envelope schema_version must be 1; inner "
            "proposal/decision objects keep their own schema_version"
        )
    events = value.get("events")
    if not isinstance(events, list) or any(
        not isinstance(item, dict) for item in events
    ):
        raise click.ClickException("research_cycle events must be an array")
    if not isinstance(value.get("parent_trace_ref"), str):
        raise click.ClickException(
            "research_cycle parent_trace_ref must be a string"
        )
