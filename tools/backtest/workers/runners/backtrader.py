"""Backtrader target-weight runner with one isolated broker per strategy."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import backtrader as bt
import pandas as pd

from .common import (
    compile_group_strategy_input,
    parse_target_weight_input,
    target_quantities,
    target_rows,
    valuation_price,
)


class _TargetWeightStrategy(bt.Strategy):
    params = (("request", None), ("target_sequence", None))

    def __init__(self) -> None:
        self._pending_targets = None
        self.equity_curve = []

    def next(self) -> None:
        row = len(self) - 1
        timestamp = self.p.request.timestamps[row]
        self.equity_curve.append((timestamp.isoformat(), float(self.broker.getvalue())))
        if self._pending_targets is not None:
            quantities = target_quantities(
                self.p.request, row, self._pending_targets, float(self.broker.getvalue())
            )
            for data in self.datas:
                self.order_target_size(
                    data=data,
                    target=float(quantities[data._name]),
                )
        self._pending_targets = self.p.target_sequence[row]


def run_target_weights(payload: Mapping[str, Any]) -> dict[str, Any]:
    request = parse_target_weight_input(payload)

    portfolios = {}
    for strategy in request.strategies:
        strategy_id = strategy.get("strategy_id", "")
        if not strategy_id or strategy_id in portfolios:
            raise ValueError("strategy ids must be non-empty and unique")
        cerebro = bt.Cerebro(stdstats=False)
        strategy_cash = float(strategy.get("initial_capital") or request.initial_cash)
        cerebro.broker.setcash(strategy_cash)
        cerebro.broker.set_coc(True)
        cerebro.broker.setcommission(
            commission=float(strategy.get("fee_rate") or 0.0), percabs=True
        )
        for instrument in request.instruments:
            values = [
                valuation_price(request, row, instrument)
                for row in range(len(request.timestamps))
            ]
            frame = pd.DataFrame(
                {
                    "open": values,
                    "high": values,
                    "low": values,
                    "close": values,
                    "volume": [1_000_000.0] * len(values),
                    "openinterest": [0.0] * len(values),
                },
                index=pd.DatetimeIndex(request.timestamps),
            )
            cerebro.adddata(bt.feeds.PandasData(dataname=frame), name=instrument)
        targets = target_rows(strategy, request.timestamps)
        target_sequence = [targets.get(timestamp) for timestamp in request.timestamps]
        cerebro.addstrategy(
            _TargetWeightStrategy,
            request=request,
            target_sequence=target_sequence,
        )
        instances = cerebro.run()
        instance = instances[0]
        portfolios[strategy_id] = {
            "initial_value": strategy_cash,
            "final_value": float(cerebro.broker.getvalue()),
            "positions": {
                data._name: float(cerebro.broker.getposition(data).size)
                for data in cerebro.datas
            },
            "equity_curve": dict(instance.equity_curve),
        }
    return {"engine": "backtrader", "portfolios": portfolios}


def run_group_strategy(payload: Mapping[str, Any]) -> dict[str, Any]:
    calculated = compile_group_strategy_input(payload)
    result = run_target_weights(calculated)
    result["target_trace"] = {
        strategy["strategy_id"]: strategy["targets"]
        for strategy in calculated["strategies"]
    }
    result["strategy_diagnostics"] = {
        strategy["strategy_id"]: strategy["diagnostics"]
        for strategy in calculated["strategies"]
    }
    return result
