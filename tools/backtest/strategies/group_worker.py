"""Translate canonical group memberships into isolated worker requests."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd


def build_group_target_weight_payload(
    group_result: Any,
    *,
    strategy_ids: Sequence[str],
    rebalance_modes: Sequence[str],
    initial_cash: float,
) -> dict[str, Any]:
    """Build equal-notional targets without consulting margin or fee matrices."""
    membership = np.asarray(group_result.membership_np, dtype=bool)
    prices = np.asarray(group_result.price_np, dtype=float)
    instruments = tuple(str(value) for value in group_result.valid_cols)
    timestamps = pd.DatetimeIndex(group_result.index_list)
    if membership.ndim != 3 or prices.shape != (len(timestamps), len(instruments)):
        raise ValueError("group result membership, price, and axes do not align")
    if membership.shape[1] != len(strategy_ids) or len(strategy_ids) != len(rebalance_modes):
        raise ValueError("one strategy id and rebalance mode are required per group")
    if initial_cash <= 0:
        raise ValueError("initial cash must be positive")

    valid_rows = np.all(np.isfinite(prices) & (prices > 0), axis=1)
    valid_positions = np.flatnonzero(valid_rows)
    if len(valid_positions) < 2:
        raise ValueError("at least two complete price rows are required")
    timestamps = timestamps[valid_positions]
    prices = prices[valid_positions]
    membership = membership[valid_positions]

    strategies = []
    for group_index, (strategy_id, rebalance_mode) in enumerate(
        zip(strategy_ids, rebalance_modes, strict=True)
    ):
        targets = {}
        previous = None
        for row_index, timestamp in enumerate(timestamps[:-1]):
            current = membership[row_index, group_index]
            should_emit = previous is None or not np.array_equal(current, previous)
            if should_emit:
                selected = np.flatnonzero(current)
                if len(selected):
                    weight = 1.0 / len(selected)
                    targets[timestamp.isoformat()] = {
                        instruments[position]: weight for position in selected
                    }
                else:
                    targets[timestamp.isoformat()] = {}
            previous = current
            if rebalance_mode == "buy_and_hold" and targets:
                break
        strategies.append({
            "strategy_id": str(strategy_id),
            "rebalance_mode": str(rebalance_mode),
            "targets": targets,
        })

    return {
        "timestamps": [timestamp.isoformat() for timestamp in timestamps],
        "instruments": list(instruments),
        "prices": {
            instrument: prices[:, index].tolist()
            for index, instrument in enumerate(instruments)
        },
        "initial_cash": float(initial_cash),
        "strategies": strategies,
    }
