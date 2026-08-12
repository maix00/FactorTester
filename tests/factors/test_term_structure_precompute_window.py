from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
import pytest

from tools.data.types import DataColumn, DataFreq
from tools.factors.expr import EvaluateContext, term_carry_annualized
from tools.products.AdjustableTermStructure import (
    TERM_DAYS_TO_MATURITY_COL,
    TERM_RANK_COL,
)


@dataclass(eq=False)
class _CountingTermProduct:
    history: pd.DataFrame
    calls: list[pd.Timestamp] = field(default_factory=list)
    name: str = "COUNTING_TERM"

    def supports_term_structure(self) -> bool:
        return True

    def get_some_data(self, _freq, copy=False):
        return self.history.copy() if copy else self.history

    def get_term_structure(self, day, depth=None):
        normalized = pd.Timestamp(day).normalize()
        self.calls.append(normalized)
        base = 100.0 + normalized.day
        curve = pd.DataFrame({
            TERM_RANK_COL: [0, 1],
            TERM_DAYS_TO_MATURITY_COL: [10, 40],
            DataColumn.CLOSE.name: [base, 0.95 * base],
        })
        return curve.head(depth) if depth is not None else curve


def test_precomputed_term_factor_uses_window_index_and_one_curve_per_day():
    history_index = pd.date_range("2024-01-01 09:00", periods=20, freq="1h")
    product = _CountingTermProduct(pd.DataFrame(
        {DataColumn.CLOSE.name: range(20)},
        index=history_index,
    ))
    window_index = pd.to_datetime(
        ["2025-01-02 09:00", "2025-01-02 10:00",
         "2025-01-03 09:00", "2025-01-03 10:00"],
    )
    preloaded = {
        (product, DataFreq.MIN1.name): pd.DataFrame(
            {DataColumn.CLOSE.name: [1.0, 2.0, 3.0, 4.0]},
            index=window_index,
        ),
    }

    result = term_carry_annualized().evaluate(ctx=EvaluateContext(
        products=[product],
        freq=DataFreq.MIN1,
        preloaded=preloaded,
    ))

    assert result.index.equals(window_index)
    assert product.calls == [
        pd.Timestamp("2025-01-02"),
        pd.Timestamp("2025-01-03"),
    ]
    expected = (1 / 0.95 - 1) * 365 / 30
    assert result[product].tolist() == pytest.approx([expected] * 4)


def test_precomputed_term_factor_preserves_timezone_multiindex():
    product = _CountingTermProduct(pd.DataFrame())
    days = pd.DatetimeIndex(
        ["2025-01-02", "2025-01-02", "2025-01-03"], tz="Asia/Shanghai",
    )
    times = pd.DatetimeIndex(
        ["2025-01-02 09:00", "2025-01-02 10:00", "2025-01-03 09:00"],
        tz="Asia/Shanghai",
    )
    window_index = pd.MultiIndex.from_arrays(
        [days, times],
        names=["DAY1", "MIN1"],
    )

    result = term_carry_annualized().evaluate(ctx=EvaluateContext(
        products=[product],
        freq=DataFreq.MIN1,
        preloaded={
            (product, DataFreq.MIN1.name): pd.DataFrame(
                {DataColumn.CLOSE.name: [1.0, 2.0, 3.0]},
                index=window_index,
            ),
        },
    ))

    assert result.index.equals(window_index)
    assert product.calls == [
        pd.Timestamp("2025-01-02"),
        pd.Timestamp("2025-01-03"),
    ]


def test_precomputed_term_factor_falls_back_without_matching_preload():
    history_index = pd.to_datetime([
        "2025-01-02 09:00",
        "2025-01-02 10:00",
        "2025-01-03 09:00",
    ])
    product = _CountingTermProduct(pd.DataFrame(
        {DataColumn.CLOSE.name: [1.0, 2.0, 3.0]},
        index=history_index,
    ))

    result = term_carry_annualized().evaluate(ctx=EvaluateContext(
        products=[product],
        freq=DataFreq.MIN1,
        preloaded={},
    ))

    assert result.index.equals(history_index)
    assert product.calls == [
        pd.Timestamp("2025-01-02"),
        pd.Timestamp("2025-01-03"),
    ]


def test_minute_window_loads_one_curve_per_trading_day():
    trading_days = pd.bdate_range("2025-01-02", periods=20)
    window_index = pd.DatetimeIndex([
        day + pd.Timedelta(minutes=minute)
        for day in trading_days
        for minute in range(240)
    ])
    product = _CountingTermProduct(pd.DataFrame())

    result = term_carry_annualized().evaluate(ctx=EvaluateContext(
        products=[product],
        freq=DataFreq.MIN1,
        preloaded={
            (product, DataFreq.MIN1.name): pd.DataFrame(
                {DataColumn.CLOSE.name: 1.0},
                index=window_index,
            ),
        },
    ))

    assert len(result) == 20 * 240
    assert product.calls == [day.normalize() for day in trading_days]
