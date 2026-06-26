from __future__ import annotations

import numpy as np
import pandas as pd

from tools.testers.backtest.engines.strategies.rebalance import (
    BuyAndHold,
    MembershipChange,
    OnFactorSignal,
    ScheduledRebalance,
)


def test_factor_frequency_and_buy_hold_are_distinct() -> None:
    timestamp = pd.Timestamp("2026-01-01")
    membership = np.array([True, False])
    factor_frequency = OnFactorSignal()
    buy_hold = BuyAndHold()

    assert factor_frequency.should_rebalance(timestamp, membership)
    assert factor_frequency.should_rebalance(timestamp, membership)
    assert buy_hold.should_rebalance(timestamp, membership)
    assert not buy_hold.should_rebalance(timestamp, membership)


def test_membership_change_and_schedule_have_explicit_clocks() -> None:
    timestamp = pd.Timestamp("2026-01-05")
    membership_change = MembershipChange()
    assert membership_change.should_rebalance(timestamp, np.array([True, False]))
    assert not membership_change.should_rebalance(timestamp, np.array([True, False]))
    assert membership_change.should_rebalance(timestamp, np.array([False, True]))

    monday = ScheduledRebalance(lambda value: value.dayofweek == 0)
    assert monday.should_rebalance(timestamp, np.array([True]))
    assert not monday.should_rebalance(timestamp + pd.Timedelta(days=1), np.array([True]))
