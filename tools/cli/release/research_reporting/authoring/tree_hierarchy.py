"""Structural rules for the report tree hierarchy."""

from __future__ import annotations


def validate_root_child(*, kind: str, parent_id: str) -> None:
    """Reserve the root level for report chapters only."""
    if parent_id == "root" and kind != "chapter":
        raise ValueError("root-level report components must be chapters")
