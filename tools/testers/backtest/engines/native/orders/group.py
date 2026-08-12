"""Non-executable order-group orchestration metadata."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class OrderGroup:
    order_group_id: str
    parent_intent_id: str
    created_at: pd.Timestamp
    child_order_ids: tuple[str, ...] = ()
    supersedes_group_id: str = ""
    execution_policy: str = "sequential_close_then_open"


def derive_group_status(statuses: tuple[str, ...]) -> str:
    if not statuses:
        return "empty"
    if all(status == "filled" for status in statuses):
        return "filled"
    if any(status == "partially_filled" for status in statuses):
        return "partially_filled"
    if any(status in {"submitted", "accepted"} for status in statuses):
        return "working"
    if any(status == "blocked" for status in statuses):
        return "waiting"
    if all(status in {"cancelled", "rejected", "expired"} for status in statuses):
        return "terminated"
    return "mixed"
