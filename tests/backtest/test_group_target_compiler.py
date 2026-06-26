from __future__ import annotations

import numpy as np
import pandas as pd

from tools.testers.backtest.engines.strategies.targets import compile_group_target_payload


def test_group_target_compiler_applies_per_strategy_policies_causally() -> None:
    index = pd.date_range("2026-01-01", periods=4, freq="D")
    membership = np.ones((4, 2, 2), dtype=bool)
    prices = np.asarray([
        [100.0, 100.0],
        [110.0, 101.0],
        [99.0, 102.01],
        [118.8, 103.0301],
    ])
    payload = compile_group_target_payload(
        timestamps=index,
        instruments=("volatile", "stable"),
        membership=membership,
        prices=prices,
        strategy_configs=(
            {
                "strategy_id": "risk",
                "allocation_policy": "inverse_volatility",
                "volatility_lookback": 2,
                "rebalance_trigger": "on_factor_signal",
                "position_policy": "rebalance_to_target",
            },
            {
                "strategy_id": "hold",
                "allocation_policy": "equal_notional",
                "rebalance_trigger": "on_factor_signal",
                "position_policy": "buy_and_hold",
            },
        ),
        initial_cash=1_000_000,
    )

    risk = payload["strategies"][0]
    hold = payload["strategies"][1]
    assert len(risk["targets"]) == 4
    assert risk["diagnostics"]["volatility_warmup_fallback_count"] == 2
    first_fallback = risk["diagnostics"]["volatility_warmup_fallbacks"][0]
    assert first_fallback["timestamp"] == index[0].isoformat()
    assert first_fallback["fallback_policy"] == "equal_notional"
    assert first_fallback["reason"] == (
        "inverse_volatility has no usable trailing volatility for "
        "volatile=nan, stable=nan"
    )
    assert all(np.isnan(value) for value in first_fallback["volatilities"].values())
    final_risk = risk["targets"][index[-1].isoformat()]
    assert final_risk["stable"] > final_risk.get("volatile", 0.0), (
        "the stable instrument must receive more inverse-volatility weight; "
        f"volatilities={risk['diagnostics']['last_volatilities']}, weights={final_risk}"
    )
    assert len(hold["targets"]) == 1
    assert set(hold["targets"][index[0].isoformat()].values()) == {0.5}


def test_equal_margin_is_explicitly_distinct_from_equal_notional() -> None:
    index = pd.date_range("2026-01-01", periods=2, freq="D")
    membership = np.ones((2, 2, 2), dtype=bool)
    payload = compile_group_target_payload(
        timestamps=index,
        instruments=("low-margin", "high-margin"),
        membership=membership,
        prices=np.full((2, 2), 100.0),
        margin_ratios=np.asarray([[0.1, 0.2], [0.1, 0.2]]),
        strategy_configs=(
            {
                "strategy_id": "notional",
                "allocation_policy": "equal_notional",
                "rebalance_trigger": "on_factor_signal",
                "position_policy": "rebalance_to_target",
            },
            {
                "strategy_id": "margin",
                "allocation_policy": "equal_margin",
                "rebalance_trigger": "on_factor_signal",
                "position_policy": "rebalance_to_target",
            },
        ),
        initial_cash=1_000_000,
    )

    notional = next(iter(payload["strategies"][0]["targets"].values()))
    margin = next(iter(payload["strategies"][1]["targets"].values()))
    assert notional == {"low-margin": 0.5, "high-margin": 0.5}
    assert np.isclose(margin["low-margin"], 2 / 3)
    assert np.isclose(margin["high-margin"], 1 / 3)


def test_long_short_is_a_peer_strategy_with_signed_target_weights() -> None:
    index = pd.date_range("2026-01-01", periods=3, freq="D")
    membership = np.asarray([
        [[True, False], [False, True]],
        [[True, False], [False, True]],
        [[False, True], [True, False]],
    ])
    payload = compile_group_target_payload(
        timestamps=index,
        instruments=("A", "B"),
        membership=membership,
        prices=np.asarray([[100.0, 100.0], [101.0, 99.0], [102.0, 98.0]]),
        signal_updates=np.ones((3, 2), dtype=bool),
        strategy_configs=({
            "strategy_id": "long-short",
            "strategy_kind": "long_short",
            "long_indices": [0],
            "short_indices": [1],
            "allocation_policy": "equal_notional",
            "rebalance_trigger": "on_factor_signal",
            "position_policy": "rebalance_to_target",
        },),
        initial_cash=1_000_000,
    )

    targets = payload["strategies"][0]["targets"]
    assert targets[index[0].isoformat()] == {"A": 0.5, "B": -0.5}
    assert targets[index[-1].isoformat()] == {"A": -0.5, "B": 0.5}


def test_long_short_skips_empty_leg_rebalances_with_diagnostics() -> None:
    index = pd.date_range("2026-01-01", periods=2, freq="D")
    membership = np.asarray([
        [[True, False], [False, False]],
        [[True, False], [False, True]],
    ])

    payload = compile_group_target_payload(
        timestamps=index,
        instruments=("A", "B"),
        membership=membership,
        prices=np.asarray([[100.0, 100.0], [101.0, 99.0]]),
        signal_updates=np.ones((2, 2), dtype=bool),
        strategy_configs=({
            "strategy_id": "long-short",
            "strategy_kind": "long_short",
            "long_indices": [0],
            "short_indices": [1],
            "allocation_policy": "equal_notional",
            "rebalance_trigger": "on_factor_signal",
            "position_policy": "rebalance_to_target",
        },),
        initial_cash=1_000_000,
    )

    strategy = payload["strategies"][0]
    assert index[0].isoformat() not in strategy["targets"]
    assert strategy["targets"][index[1].isoformat()] == {"A": 0.5, "B": -0.5}
    assert strategy["diagnostics"]["long_short_empty_leg_count"] == 1
    assert strategy["diagnostics"]["long_short_empty_legs"][0] == {
        "timestamp": index[0].isoformat(),
        "long_count": 1,
        "short_count": 0,
    }


def test_long_short_nets_realized_membership_overlap() -> None:
    index = pd.date_range("2026-01-01", periods=1, freq="D")
    membership = np.asarray([
        [[True, True, False], [False, True, True]],
    ])

    payload = compile_group_target_payload(
        timestamps=index,
        instruments=("A", "B", "C"),
        membership=membership,
        prices=np.asarray([[100.0, 100.0, 100.0]]),
        signal_updates=np.ones((1, 2), dtype=bool),
        strategy_configs=({
            "strategy_id": "long-short",
            "strategy_kind": "long_short",
            "long_indices": [0],
            "short_indices": [1],
            "allocation_policy": "equal_notional",
            "rebalance_trigger": "on_factor_signal",
            "position_policy": "rebalance_to_target",
        },),
        initial_cash=1_000_000,
    )

    strategy = payload["strategies"][0]
    assert strategy["targets"][index[0].isoformat()] == {"A": 0.5, "C": -0.5}
    assert strategy["diagnostics"]["long_short_overlap_count"] == 1
    assert strategy["diagnostics"]["long_short_overlaps"][0]["instruments"] == ["B"]
