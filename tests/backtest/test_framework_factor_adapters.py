from __future__ import annotations

import pandas as pd

from tools.backtest.adapters.backtrader import (
    BacktraderFactorAdapter,
    apply_target_weights as apply_backtrader_weights,
)
from tools.backtest.adapters.frameworks import IncrementalFactorSource
from tools.backtest.adapters.qlib import QlibFactorAdapter
from tools.backtest.adapters.zipline import (
    ZiplineFactorAdapter,
    apply_target_weights as apply_zipline_weights,
)
from tools.data.types import DataColumn
from tools.factors.expr import ColumnRef


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
