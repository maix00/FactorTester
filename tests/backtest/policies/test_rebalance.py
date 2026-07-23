from __future__ import annotations

import pytest

from tools.testers.backtest.policies.rebalance import (
    reuse_buy_and_hold_target,
    reuse_unchanged_membership_target,
    validate_rebalance_configuration,
)


def test_buy_and_hold_reuses_only_an_established_target():
    assert reuse_buy_and_hold_target("rebalance_to_target", {"A": 1.0}) is None
    assert reuse_buy_and_hold_target("buy_and_hold", None) is None
    assert reuse_buy_and_hold_target("buy_and_hold", {"A": 1.0}) == ({"A": 1.0}, "buy_and_hold_established_target")


def test_membership_trigger_reuses_target_only_when_selection_is_unchanged():
    assert reuse_unchanged_membership_target(
        "membership_change", {"A"}, {"A"}, {"A": 1.0}
    ) == ({"A": 1.0}, "membership_unchanged")
    assert reuse_unchanged_membership_target(
        "membership_change", {"B"}, {"A"}, {"A": 1.0}
    ) is None
    assert reuse_unchanged_membership_target("on_factor_signal", {"A"}, {"A"}, {"A": 1.0}) is None


def test_scheduled_trigger_requires_a_calendar_flow():
    with pytest.raises(NotImplementedError, match="calendar-driven"):
        validate_rebalance_configuration("scheduled", allocation_is_membership_only=True)


def test_membership_trigger_rejects_allocation_that_can_drift():
    with pytest.raises(ValueError, match="inverse_volatility"):
        validate_rebalance_configuration(
            "membership_change",
            allocation_is_membership_only=False,
            allocation_name="inverse_volatility",
        )
