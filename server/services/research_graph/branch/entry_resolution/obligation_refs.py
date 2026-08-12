"""Decision-blocking obligations mapped to entry requirements."""

from __future__ import annotations

from typing import Any

from ..entry_requirements import checkpoint_obligations


def blocking_obligation_refs(
    *,
    checkpoint: dict[str, Any] | None,
    requirement_refs: list[str],
) -> list[str]:
    selected = set(requirement_refs)
    return sorted({
        f"obligation:{item['obligation_id']}"
        for item in checkpoint_obligations(checkpoint)
        if str(item.get("obligation_id") or "")
        and item.get("materiality") == "decision_blocking"
        and item.get("status") in {"open", "reopened"}
        and selected.intersection(
            str(ref).removeprefix("requirement:")
            for ref in item.get("requirement_refs") or []
        )
    })
