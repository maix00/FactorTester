"""Final byte fitting for a compact Research Graph context."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import orjson


def with_context_bytes(context: dict[str, Any]) -> int:
    context["context_bytes"] = 0
    for _ in range(3):
        context["context_bytes"] = len(orjson.dumps(context))
    return len(orjson.dumps(context))


def fit_compacted_context(
    context: dict[str, Any], *, target_bytes: int,
) -> dict[str, Any]:
    """Remove optional prose in stable stages while preserving routing IDs."""
    value = deepcopy(context)
    if with_context_bytes(value) <= target_bytes:
        return value
    value["packet_compaction"] = {
        "mode": "lazy_contract_details",
        "detail_command": (
            "factortester research-graph requirement-detail "
            "<instance> <branch> <requirement-id>"
        ),
    }
    if with_context_bytes(value) <= target_bytes:
        return value
    for action in value.get("next_actions") or []:
        if isinstance(action, dict):
            action.pop("reason", None)
    if with_context_bytes(value) <= target_bytes:
        return value
    # ``instruction`` is the immediate action; ``then`` is optional look-ahead
    # and remains available from the node/edge detail packet.
    for action in value.get("next_actions") or []:
        if isinstance(action, dict):
            action.pop("then", None)
    if with_context_bytes(value) <= target_bytes:
        return value
    for requirement in value.get("entry_requirements") or []:
        if isinstance(requirement, dict):
            requirement.pop("detail_ref", None)
    if with_context_bytes(value) <= target_bytes:
        return value
    cycle = value.get("research_cycle") or {}
    for field in ("obligations", "open_obligations"):
        for obligation in cycle.get(field) or []:
            if isinstance(obligation, dict):
                obligation.pop("question_summary", None)
                obligation.pop("detail_ref", None)
    if with_context_bytes(value) <= target_bytes:
        return value
    # Materiality remains available from the cycle-object detail endpoint.
    # Keep the action instruction because it tells the Agent how to use the
    # routing-critical tuple instead of merely exposing a command.
    for field in ("obligations", "open_obligations"):
        for obligation in cycle.get(field) or []:
            if isinstance(obligation, dict):
                obligation.pop("materiality", None)
    if with_context_bytes(value) <= target_bytes:
        return value
    # Requirement IDs are already present in ``entry_requirements``.  Remove
    # only that duplicate list; the action instruction remains in-context.
    for action in value.get("next_actions") or []:
        if isinstance(action, dict):
            action.pop("requirement_ids", None)
    return value
