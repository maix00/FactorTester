from __future__ import annotations

import numpy as np
import pandas as pd


def _raw_returns(prices: pd.Series, periods: int) -> pd.Series:
    return prices / prices.shift(periods) - 1.0


def test_close_to_close_next_period_return_aligns_to_signal_bar():
    close = pd.Series([100.0, 102.0, 101.0, 105.0])
    re = _raw_returns(close, 1).shift(-1)

    assert np.isnan(re.iloc[-1])
    assert re.iloc[0] == close.iloc[1] / close.iloc[0] - 1.0
    assert re.iloc[1] == close.iloc[2] / close.iloc[1] - 1.0


def test_open_to_open_next_period_return_starts_after_signal_bar():
    open_ = pd.Series([100.0, 101.0, 104.0, 108.0])
    re = _raw_returns(open_, 1).shift(-1).shift(-1)

    assert re.iloc[0] == open_.iloc[2] / open_.iloc[1] - 1.0
    assert re.iloc[1] == open_.iloc[3] / open_.iloc[2] - 1.0
    assert np.isnan(re.iloc[-1])


def test_future_price_mutation_cannot_change_past_close_return():
    close = pd.Series([100.0, 102.0, 101.0, 105.0])
    original = _raw_returns(close, 1).shift(-1)

    mutated = close.copy()
    mutated.iloc[3] = 10_000.0
    changed = _raw_returns(mutated, 1).shift(-1)

    assert changed.iloc[0] == original.iloc[0]
    assert changed.iloc[1] == original.iloc[1]
