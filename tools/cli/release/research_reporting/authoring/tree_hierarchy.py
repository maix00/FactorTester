"""Structural rules for the report tree hierarchy."""

from __future__ import annotations

_CONTENT = {"entry", "list", "table", "image", "code", "math", "result"}
_ALLOWED = {
    "root": {"chapter"},
    "chapter": {"section", "special", *_CONTENT},
    "section": {"subsection", "special", *_CONTENT},
    "subsection": {"special", *_CONTENT},
    "special": {"section", "subsection", "special", *_CONTENT},
}


def validate_root_child(*, kind: str, parent_id: str) -> None:
    """Reserve the root level for report chapters only."""
    if parent_id == "root" and kind != "chapter":
        raise ValueError("root-level report components must be chapters")


def validate_parent_child(*, parent_kind: str, child_kind: str) -> None:
    allowed = _ALLOWED.get(parent_kind)
    if allowed is None or child_kind not in allowed:
        raise ValueError(
            f"report parent kind {parent_kind} cannot contain {child_kind}"
        )
