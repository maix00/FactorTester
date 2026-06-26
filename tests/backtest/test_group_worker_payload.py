from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from tools.testers.backtest.engines.strategies.group_worker import build_group_target_weight_payload


def test_group_worker_payload_is_equal_notional_and_keeps_rebalance_semantics() -> None:
    result = SimpleNamespace(
        membership_np=np.array([
            [[True, True, False], [False, False, True]],
            [[True, True, False], [False, False, True]],
            [[False, True, True], [True, False, False]],
        ]),
        price_np=np.array([
            [100.0, 200.0, 300.0],
            [101.0, 201.0, 301.0],
            [102.0, 202.0, 302.0],
        ]),
        valid_cols=["A", "B", "C"],
        index_list=pd.date_range("2026-01-01", periods=3, freq="min"),
        margin_ratio_mat=np.array([[0.05, 0.50, 0.90]]),
    )

    payload = build_group_target_weight_payload(
        result,
        strategy_ids=("group-1", "group-2"),
        rebalance_triggers=("on_factor_signal", "on_factor_signal"),
        position_policies=("rebalance_to_target", "buy_and_hold"),
        initial_cash=1_000_000.0,
    )

    first, second = payload["strategies"]
    assert first["rebalance_trigger"] == "on_factor_signal"
    assert first["position_policy"] == "rebalance_to_target"
    assert list(first["targets"].values()) == [{"A": 0.5, "B": 0.5}]
    assert second["rebalance_trigger"] == "on_factor_signal"
    assert second["position_policy"] == "buy_and_hold"
    assert list(second["targets"].values()) == [{"C": 1.0}]
