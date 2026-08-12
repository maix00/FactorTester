"""State-aware target reuse and rebalance validation tools."""

from __future__ import annotations

from collections.abc import Set
from typing import Any

TargetReuse = tuple[dict[Any, float], str]


def reuse_buy_and_hold_target(
    position_policy: str,
    established_target: dict[Any, float] | None,
) -> TargetReuse | None:
    if position_policy == "buy_and_hold" and established_target is not None:
        return established_target, "buy_and_hold_established_target"
    return None


def reuse_unchanged_membership_target(
    rebalance_trigger: str,
    selected: Set[Any],
    previous_selection: Set[Any] | None,
    established_target: dict[Any, float] | None,
) -> TargetReuse | None:
    if rebalance_trigger == "membership_change" and previous_selection == selected:
        return established_target or {}, "membership_unchanged"
    return None


def validate_rebalance_configuration(
    rebalance_trigger: str,
    *,
    allocation_is_membership_only: bool,
    allocation_name: str = "allocation",
) -> None:
    if rebalance_trigger == "scheduled":
        raise NotImplementedError(
            'rebalance_trigger="scheduled" requires a calendar-driven SIGNAL '
            "schedule independent of factor timing"
        )
    if rebalance_trigger == "membership_change" and not allocation_is_membership_only:
        raise ValueError(
            'rebalance_trigger="membership_change" only reduces turnover when target '
            "weights are a pure function of membership; "
            f"allocation_policy={allocation_name!r} can drift while membership is unchanged"
        )
