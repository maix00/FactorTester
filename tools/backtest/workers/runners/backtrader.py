"""Backtrader target-weight runner with one isolated broker per strategy."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import backtrader as bt
import pandas as pd


class _TargetWeightStrategy(bt.Strategy):
    params = (("targets", None),)

    def next(self) -> None:
        timestamp = pd.Timestamp(self.datas[0].datetime.datetime(0)).isoformat()
        weights = self.p.targets.get(timestamp)
        if weights is None:
            return
        for data in self.datas:
            self.order_target_percent(data=data, target=float(weights.get(data._name, 0.0)))


def run_target_weights(payload: Mapping[str, Any]) -> dict[str, Any]:
    timestamps = [pd.Timestamp(value) for value in payload.get("timestamps", ())]
    instruments = tuple(payload.get("instruments", ()))
    prices = payload.get("prices", {})
    strategies = payload.get("strategies", ())
    initial_cash = float(payload.get("initial_cash", 0.0))
    if not timestamps or not instruments or not strategies or initial_cash <= 0:
        raise ValueError("target-weight run requires timestamps, instruments, strategies, and positive cash")

    portfolios = {}
    for strategy in strategies:
        strategy_id = strategy.get("strategy_id", "")
        if not strategy_id or strategy_id in portfolios:
            raise ValueError("strategy ids must be non-empty and unique")
        cerebro = bt.Cerebro(stdstats=False)
        cerebro.broker.setcash(initial_cash)
        for instrument in instruments:
            values = prices.get(instrument)
            if not isinstance(values, list) or len(values) != len(timestamps):
                raise ValueError(f"price length mismatch for {instrument}")
            frame = pd.DataFrame(
                {
                    "open": values,
                    "high": values,
                    "low": values,
                    "close": values,
                    "volume": [1_000_000.0] * len(values),
                    "openinterest": [0.0] * len(values),
                },
                index=pd.DatetimeIndex(timestamps),
            )
            cerebro.adddata(bt.feeds.PandasData(dataname=frame), name=instrument)
        targets = strategy.get("targets", {})
        cerebro.addstrategy(_TargetWeightStrategy, targets=targets)
        cerebro.run()
        portfolios[strategy_id] = {
            "initial_value": initial_cash,
            "final_value": float(cerebro.broker.getvalue()),
        }
    return {"engine": "backtrader", "portfolios": portfolios}
