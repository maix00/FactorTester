"""Backtrader target-weight runner with one isolated broker per strategy."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import backtrader as bt
import numpy as np
import pandas as pd

from .common import (
    market_rule_diagnostics,
    parse_group_strategy_input,
    parse_target_weight_input,
    target_quantities,
    target_rows,
    valuation_price,
)


class _TargetWeightStrategy(bt.Strategy):
    params = (("request", None), ("target_sequence", None), ("strategy_config", None))

    def __init__(self) -> None:
        self._pending_targets = None
        self.equity_curve = []
        self._open_orders = {}
        self.position_curve = {}

    def notify_order(self, order) -> None:
        if not order.alive() and self._open_orders.get(order.data._name) is order:
            del self._open_orders[order.data._name]

    def next(self) -> None:
        row = len(self) - 1
        timestamp = self.p.request.timestamps[row]
        self.equity_curve.append((timestamp.isoformat(), float(self.broker.getvalue())))
        self.position_curve[timestamp.isoformat()] = {
            data._name: float(self.getposition(data).size) for data in self.datas
        }
        if self._pending_targets is not None:
            quantities = target_quantities(
                self.p.request,
                row,
                self._pending_targets,
                float(self.broker.getvalue()),
                self.p.strategy_config,
            )
            for data in self.datas:
                self.order_target_size(
                    data=data,
                    target=float(quantities[data._name]),
                )
        self._pending_targets = self.p.target_sequence[row]


class _GroupMembershipStrategy(bt.Strategy):
    params = (
        ("request", None),
        ("strategy_config", None),
        ("calculator", None),
        ("memberships", None),
        ("signal_updates", None),
        ("progress_callback", None),
    )

    def __init__(self) -> None:
        self._pending_targets = None
        self.equity_curve = []
        self._open_orders = {}
        self.position_curve = {}

    def notify_order(self, order) -> None:
        if not order.alive() and self._open_orders.get(order.data._name) is order:
            del self._open_orders[order.data._name]

    def next(self) -> None:
        row = len(self) - 1
        timestamp = self.p.request.timestamps[row]
        self.equity_curve.append((timestamp.isoformat(), float(self.broker.getvalue())))
        self.position_curve[timestamp.isoformat()] = {
            data._name: float(self.getposition(data).size) for data in self.datas
        }
        target = self.p.calculator.update(
            timestamp,
            np.asarray([
                self.p.request.prices[name][row]
                for name in self.p.request.instruments
            ]),
            self.p.memberships[row],
            self.p.signal_updates[row],
            np.asarray(self.p.request.margin_ratios[row]),
        )
        if target is not None:
            quantities = target_quantities(
                self.p.request,
                row,
                target,
                float(self.broker.getvalue()),
                self.p.strategy_config,
            )
            for data in self.datas:
                previous = self._open_orders.pop(data._name, None)
                if previous is not None and previous.alive():
                    self.cancel(previous)
                order = self.order_target_size(
                    data=data, target=float(quantities[data._name])
                )
                if order is not None:
                    self._open_orders[data._name] = order
        if self.p.progress_callback is not None:
            self.p.progress_callback(row + 1, len(self.p.request.timestamps), timestamp)


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
        liquidity_mode = str(strategy.get("liquidity_mode") or "infinite")
        if liquidity_mode == "volume_participation":
            cerebro.broker.set_filler(bt.fillers.FixedBarPerc(
                perc=float(strategy.get("participation_rate") or 0.0) * 100.0
            ))
        elif liquidity_mode != "infinite":
            raise ValueError(f"unsupported liquidity mode: {liquidity_mode}")
        slippage_mode = str(strategy.get("slippage_mode") or "none")
        if slippage_mode == "fixed_bps":
            cerebro.broker.set_slippage_perc(
                float(strategy.get("slippage_bps") or 0.0) / 10_000.0
            )
        elif slippage_mode != "none":
            raise ValueError(f"unsupported slippage mode: {slippage_mode}")
        for instrument in request.instruments:
            values = [
                valuation_price(request, row, instrument)
                for row in range(len(request.timestamps))
            ]
            frame = pd.DataFrame(
                {
                    "open": values,
                    "high": [value * 2.0 for value in values],
                    "low": [value * 0.5 for value in values],
                    "close": values,
                    "volume": (
                        list(request.volumes[instrument])
                        if request.volumes is not None else [1_000_000.0] * len(values)
                    ),
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
            strategy_config=strategy,
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
            "position_curve": dict(instance.position_curve),
        }
    return {"engine": "backtrader", "portfolios": portfolios}


def run_group_strategy(payload: Mapping[str, Any], progress=None) -> dict[str, Any]:
    request, memberships, updates, calculators = parse_group_strategy_input(payload)
    portfolios = {}
    for strategy_position, (strategy, calculator) in enumerate(
        zip(request.strategies, calculators, strict=True)
    ):
        cerebro = bt.Cerebro(stdstats=False)
        strategy_cash = float(strategy.get("initial_capital") or request.initial_cash)
        cerebro.broker.setcash(strategy_cash)
        cerebro.broker.set_coc(True)
        cerebro.broker.setcommission(
            commission=float(strategy.get("fee_rate") or 0.0), percabs=True
        )
        liquidity_mode = str(strategy.get("liquidity_mode") or "infinite")
        if liquidity_mode == "volume_participation":
            cerebro.broker.set_filler(bt.fillers.FixedBarPerc(
                perc=float(strategy.get("participation_rate") or 0.0) * 100.0
            ))
        elif liquidity_mode != "infinite":
            raise ValueError(f"unsupported liquidity mode: {liquidity_mode}")
        slippage_mode = str(strategy.get("slippage_mode") or "none")
        if slippage_mode == "fixed_bps":
            cerebro.broker.set_slippage_perc(
                float(strategy.get("slippage_bps") or 0.0) / 10_000.0
            )
        elif slippage_mode != "none":
            raise ValueError(f"unsupported slippage mode: {slippage_mode}")
        for instrument in request.instruments:
            values = [
                valuation_price(request, row, instrument)
                for row in range(len(request.timestamps))
            ]
            frame = pd.DataFrame(
                {
                    "open": values,
                    "high": [value * 2.0 for value in values],
                    "low": [value * 0.5 for value in values],
                    "close": values,
                    "volume": (
                        list(request.volumes[instrument])
                        if request.volumes is not None else [1_000_000.0] * len(values)
                    ),
                    "openinterest": [0.0] * len(values),
                },
                index=pd.DatetimeIndex(request.timestamps),
            )
            cerebro.adddata(bt.feeds.PandasData(dataname=frame), name=instrument)
        cerebro.addstrategy(
            _GroupMembershipStrategy,
            request=request,
            strategy_config=strategy,
            calculator=calculator,
            memberships=memberships,
            signal_updates=updates,
            progress_callback=progress if strategy_position == 0 else None,
        )
        instance = cerebro.run()[0]
        portfolios[calculator.strategy_id] = {
            "initial_value": strategy_cash,
            "final_value": float(cerebro.broker.getvalue()),
            "positions": {
                data._name: float(cerebro.broker.getposition(data).size)
                for data in cerebro.datas
            },
            "equity_curve": dict(instance.equity_curve),
            "position_curve": dict(instance.position_curve),
        }
    return {
        "engine": "backtrader",
        "portfolios": portfolios,
        "target_trace": {item.strategy_id: item.target_trace for item in calculators},
        "strategy_diagnostics": {
            item.strategy_id: {**item.diagnostics, **market_rule_diagnostics(payload)}
            for item in calculators
        },
    }
