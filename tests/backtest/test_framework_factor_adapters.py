from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tools.testers.backtest.engines.adapters.backtrader import (
    BacktraderFactorAdapter,
    apply_target_weights as apply_backtrader_weights,
)
from tools.testers.backtest.engines.adapters.factor_step import FactorStepAdapter
from tools.testers.backtest.engines.adapters.frameworks import (
    IncrementalFactorSource,
    PrecomputedFactorSource,
)
from tools.testers.backtest.engines.adapters.qlib import QlibFactorAdapter
from tools.testers.backtest.engines.adapters.zipline import (
    ZiplineFactorAdapter,
    apply_target_weights as apply_zipline_weights,
)
from tools.data.types import DataColumn, DataFreq
from tools.factors.expr import ColumnRef, EvaluateContext


class Line:
    def __init__(self, value: float) -> None:
        self.value = value

    def __getitem__(self, index: int) -> float:
        assert index == 0
        return self.value


class Feed:
    def __init__(self, close: float) -> None:
        self.close = Line(close)


class BarData:
    def __init__(self, close: float) -> None:
        self.close = close

    def current(self, asset: object, field: str) -> float:
        assert field == "close"
        return self.close


class Exchange:
    def __init__(self, close: float) -> None:
        self.close = close

    def get_quote_info(self, stock_id, start_time, end_time, field):
        assert field == "$close"
        return self.close


def test_framework_callbacks_execute_the_same_incremental_factor() -> None:
    expression = ColumnRef(DataColumn.CLOSE).rolling_mean(2)
    source = IncrementalFactorSource(expression)
    backtrader = BacktraderFactorAdapter("mean", source, ("A",))
    zipline = ZiplineFactorAdapter("mean", source, ("A",))
    qlib = QlibFactorAdapter("mean", source, ("A",))
    adapters = (
        lambda timestamp, close: backtrader.on_next(
            {"A": Feed(close)}, timestamp
        ),
        lambda timestamp, close: zipline.on_handle_data(
            timestamp, BarData(close), {"A": object()}
        ),
        lambda timestamp, close: qlib.on_generate_trade_decision(
            Exchange(close), timestamp
        ),
    )
    timestamps = pd.date_range("2026-01-01 09:01", periods=2, freq="min")

    values = [
        [adapter(timestamp, close).values["A"] for timestamp, close in zip(timestamps, (2.0, 4.0))]
        for adapter in adapters
    ]

    assert values == [[2.0, 3.0], [2.0, 3.0], [2.0, 3.0]]


def test_factor_step_adapter_live_and_precomputed_nested_factor_match() -> None:
    products = ("A", "B")
    timestamps = pd.date_range("2026-01-01 09:00", periods=8, freq="min")
    close = pd.DataFrame(
        {
            "A": [10.0, 11.0, 13.0, 12.0, 15.0, 16.0, 14.0, 18.0],
            "B": [20.0, 18.0, 19.0, 17.0, 21.0, 20.0, 23.0, 22.0],
        },
        index=timestamps,
    )
    open_ = close - 0.5
    preloaded = {
        (product, DataFreq.MIN1.name): pd.DataFrame(
            {"CLOSE": close[product], "OPEN": open_[product]},
            index=timestamps,
        )
        for product in products
    }
    expression = (
        (ColumnRef(DataColumn.CLOSE).rolling_mean(3)
         - ColumnRef(DataColumn.OPEN).rolling_ema(2))
        .rolling_mean(2)
    )
    precomputed = expression.evaluate(ctx=EvaluateContext(
        products=products,
        freq=DataFreq.MIN1,
        cache={},
        preloaded=preloaded,
    ))
    precomputed_adapter = FactorStepAdapter(
        "nested", PrecomputedFactorSource(precomputed), products,
    )
    live_adapter = FactorStepAdapter(
        "nested", IncrementalFactorSource(expression), products,
    )

    for row_index, timestamp in enumerate(timestamps):
        expected = precomputed_adapter.update(timestamp, {}).values
        actual = live_adapter.update(timestamp, {
            product: {
                "CLOSE": float(close.iloc[row_index][product]),
                "OPEN": float(open_.iloc[row_index][product]),
            }
            for product in products
        }).values
        for product in products:
            assert np.isnan(actual[product]) == np.isnan(expected[product])
            if np.isfinite(expected[product]):
                assert actual[product] == pytest.approx(expected[product], abs=1e-12)


class TargetHost:
    def __init__(self) -> None:
        self.calls = []

    def order_target_percent(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return len(self.calls)


def test_target_weight_adapters_call_framework_order_helpers() -> None:
    backtrader = TargetHost()
    zipline = TargetHost()
    feeds = {"A": object(), "B": object()}
    assets = {"A": object(), "B": object()}

    assert apply_backtrader_weights(
        backtrader, {"A": 0.6, "B": 0.4}, feeds
    ) == [1, 2]
    assert apply_zipline_weights(
        zipline, {"A": 0.6, "B": 0.4}, assets
    ) == [1, 2]
    assert backtrader.calls[0] == ((), {"data": feeds["A"], "target": 0.6})
    assert zipline.calls[0] == ((assets["A"], 0.6), {})
