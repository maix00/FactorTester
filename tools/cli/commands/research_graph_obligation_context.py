"""Refresh volatile node context without treating it as ledger identity."""

from __future__ import annotations

from typing import Any

from copy import deepcopy


_STABLE_BRANCH_FIELDS = {
    "branch_ref", "graph_ref", "current_node", "checkpoint_ref",
}


def refresh_context_metadata(
    ledger: dict[str, Any], *, expected_branch: dict[str, str],
) -> dict[str, Any]:
    """Refresh context_ref after checking the stable Graph checkpoint."""
    current = ledger["branch"]
    if current == expected_branch:
        return ledger
    if any(
        current.get(field) != expected_branch.get(field)
        for field in _STABLE_BRANCH_FIELDS
    ):
        raise ValueError(
            "obligation ledger branch/node/checkpoint is stale; reconcile "
            "the accepted transition before making another obligation change"
        )
    new_context = str(expected_branch.get("context_ref") or "")
    if not new_context:
        raise ValueError("obligation ledger context identity is invalid")
    value = deepcopy(ledger)
    value["branch"]["context_ref"] = new_context
    return value
