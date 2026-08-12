"""Shared identity fields for resumable branch-side frames."""

from __future__ import annotations

from typing import Any


def normalized_continuation_identity(
    *,
    resume_node: Any,
    origin_ref: Any,
) -> dict[str, str]:
    """Normalize identity only; each frame keeps its own business semantics."""
    return {
        "resume_node": str(resume_node or ""),
        "origin_ref": str(origin_ref or ""),
    }
