"""Backtrader target-weight runner with one isolated broker per strategy."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import backtrader as bt
import numpy as np
import pandas as pd

from .common import (
    capacity_limited_deltas,
    execution_trace_entry,
    execution_price,
    market_rule_diagnostics,
    parse_group_strategy_input,
    parse_target_weight_input,
    position_value_snapshot,
    require_broker_policies,
    setting_fallback_diagnostics,
    target_quantities,
    target_rows,
    valuation_price,
    should_report_progress,
)


class _TargetWeightStrategy(bt.Strategy):
    params = (("request", None), ("target_sequence", None), ("strategy_config", None))

    def __init__(self) -> None:
        self._pending_targets = None
        self.equity_curve = []
        self._open_orders = {}
        self.position_curve = {}
        self.notional_curve = {}
        self.margin_curve = {}
        self.execution_trace = {}

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
        notional_values, margin_values = position_value_snapshot(
            self.p.request,
            row,
            self.p.strategy_config,
            self.position_curve[timestamp.isoformat()],
        )
        self.notional_curve[timestamp.isoformat()] = notional_values
        if margin_values is not None:
            self.margin_curve[timestamp.isoformat()] = margin_values
        if self._pending_targets is not None:
            quantities = target_quantities(
                self.p.request,
                row,
                self._pending_targets,
                float(self.broker.getvalue()),
                self.p.strategy_config,
            )
            targets = _backtrader_executable_target_sizes(
                self.p.request,
                row,
                self.p.strategy_config,
                quantities,
                {data._name: float(self.getposition(data).size) for data in self.datas},
                float(self.broker.getcash()),
            )
            current_positions = {
                data._name: float(self.getposition(data).size) for data in self.datas
            }
            self.execution_trace[timestamp.isoformat()] = execution_trace_entry(
                self.p.request,
                row,
                self.p.strategy_config,
                current_positions,
                {
                    name: float(targets[name]) - float(current_positions.get(name, 0.0))
                    for name in targets
                },
                float(self.broker.getcash()),
            )
            for sell_first in (True, False):
                for data in self.datas:
                    name = data._name
                    current = float(self.getposition(data).size)
                    delta = targets[name] - current
                    if abs(delta) <= 1e-12 or (delta < 0) != sell_first:
                        continue
                    self.order_target_size(data=data, target=float(targets[name]))
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
        self.notional_curve = {}
        self.margin_curve = {}
        self.execution_trace = {}

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
        notional_values, margin_values = position_value_snapshot(
            self.p.request,
            row,
            self.p.strategy_config,
            self.position_curve[timestamp.isoformat()],
        )
        self.notional_curve[timestamp.isoformat()] = notional_values
        if margin_values is not None:
            self.margin_curve[timestamp.isoformat()] = margin_values
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
            targets = _backtrader_executable_target_sizes(
                self.p.request,
                row,
                self.p.strategy_config,
                quantities,
                {data._name: float(self.getposition(data).size) for data in self.datas},
                float(self.broker.getcash()),
            )
            current_positions = {
                data._name: float(self.getposition(data).size) for data in self.datas
            }
            trace_timestamp = self.p.request.timestamps[
                min(row + 1, len(self.p.request.timestamps) - 1)
            ]
            deltas = {
                name: float(targets[name]) - float(current_positions.get(name, 0.0))
                for name in targets
            }
            if any(abs(delta) > 1e-12 for delta in deltas.values()):
                self.execution_trace[trace_timestamp.isoformat()] = execution_trace_entry(
                    self.p.request,
                    row,
                    self.p.strategy_config,
                    current_positions,
                    deltas,
                    float(self.broker.getcash()),
                )
            for sell_first in (True, False):
                for data in self.datas:
                    name = data._name
                    previous = self._open_orders.pop(name, None)
                    if previous is not None and previous.alive():
                        self.cancel(previous)
                    current = float(self.getposition(data).size)
                    delta = targets[name] - current
                    if abs(delta) <= 1e-12 or (delta < 0) != sell_first:
                        continue
                    order = self.order_target_size(data=data, target=float(targets[name]))
                    if order is not None:
                        self._open_orders[name] = order
        if self.p.progress_callback is not None and should_report_progress(
            row + 1, len(self.p.request.timestamps)
        ):
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
            "notional_curve": dict(instance.notional_curve),
            "margin_curve": dict(instance.margin_curve),
            "execution_trace": dict(instance.execution_trace),
        }
    return {"engine": "backtrader", "portfolios": portfolios}


def _configure_backtrader_broker(cerebro, strategy: Mapping[str, Any]) -> None:
    """Map ADR-028 broker policy selectors onto Backtrader's broker.

    - matching_policy=next_bar_open_full_fill: Backtrader market orders fill
      at the NEXT bar's open by default — coc stays False.
    - cancel_policy=replace_pending_same_product: implemented inside
      _GroupMembershipStrategy.next() via self.cancel(previous).
    - cash_policy=rescale_buy_orders + min_lot_policy=floor_to_lot:
      implemented by _backtrader_executable_target_sizes before ordering.
    - fill_cap_policy: no_cap → no filler; volume_participation →
      bt.fillers.FixedBarPerc.
    """
    require_broker_policies(
        strategy,
        engine="backtrader",
        supported={"fill_cap_policy": frozenset({"no_cap", "volume_participation"})},
    )
    cerebro.broker.set_coc(False)
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
    cerebro.broker.setcommission(
        commission=float(strategy.get("fee_rate") or 0.0), percabs=True
    )


def run_group_strategy(payload: Mapping[str, Any], progress=None) -> dict[str, Any]:
    """Event-driven group replay through Backtrader's own Cerebro engine.

    Each strategy runs a real bt.Strategy (_GroupMembershipStrategy): targets
    are computed inside next() bar callbacks, stale open orders are cancelled
    via the broker (replace_pending_same_product), and fills happen through
    Backtrader's order/broker lifecycle at the next bar's open — the same
    event semantics ADR-029 fixes for native (target on SIGNAL, fill on the
    following ORDER)."""
    request, memberships, updates, calculators = parse_group_strategy_input(payload)
    portfolios = {}
    total_replay_steps = len(request.timestamps) * len(request.strategies)
    for strategy_position, (strategy, calculator) in enumerate(
        zip(request.strategies, calculators, strict=True)
    ):
        cerebro = bt.Cerebro(stdstats=False)
        strategy_cash = float(strategy.get("initial_capital") or request.initial_cash)
        cerebro.broker.setcash(strategy_cash)
        _configure_backtrader_broker(cerebro, strategy)
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

        def _progress_callback(completed, total, timestamp, _offset=strategy_position):
            if progress is not None:
                progress(
                    _offset * len(request.timestamps) + completed,
                    total_replay_steps,
                    timestamp,
                )

        cerebro.addstrategy(
            _GroupMembershipStrategy,
            request=request,
            strategy_config=strategy,
            calculator=calculator,
            memberships=memberships,
            signal_updates=updates,
            progress_callback=_progress_callback if progress is not None else None,
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
            "notional_curve": dict(instance.notional_curve),
            "margin_curve": dict(instance.margin_curve),
            "execution_trace": dict(instance.execution_trace),
            "execution_trace_count": len(instance.execution_trace),
        }
    return {
        "engine": "backtrader",
        "portfolios": portfolios,
        "target_trace": {item.strategy_id: item.target_trace for item in calculators},
        "execution_trace": {
            strategy_id: portfolio.get("execution_trace", {})
            for strategy_id, portfolio in portfolios.items()
        },
        "strategy_diagnostics": {
            item.strategy_id: {
                **item.diagnostics,
                **market_rule_diagnostics(payload),
                **setting_fallback_diagnostics(strategy),
            }
            for item, strategy in zip(calculators, request.strategies, strict=True)
        },
        "event_count": len(request.timestamps),
        "signal_kind": payload.get("signal_kind"),
    }


def _backtrader_executable_target_sizes(
    request,
    row: int,
    strategy: Mapping[str, Any],
    desired: Mapping[str, float],
    current: Mapping[str, float],
    cash: float,
) -> dict[str, float]:
    deltas = capacity_limited_deltas(request, row, strategy, desired, current)
    fee_rate = float(strategy.get("fee_rate") or 0.0)
    available = float(cash)
    buy_cost = 0.0
    for instrument, delta in deltas.items():
        if abs(delta) <= 1e-12:
            continue
        price = execution_price(valuation_price(request, row, instrument), delta, strategy)
        notional = abs(delta) * price
        if delta < 0:
            available += notional - notional * fee_rate
        else:
            buy_cost += notional * (1.0 + fee_rate)
    if buy_cost > max(available, 0.0) + 1e-9:
        if buy_cost <= 0.0 or available <= 0.0:
            deltas = {
                instrument: (delta if delta < 0 else 0.0)
                for instrument, delta in deltas.items()
            }
        else:
            scale = available / buy_cost
            adjusted = dict(deltas)
            for position, instrument in enumerate(request.instruments):
                delta = adjusted.get(instrument, 0.0)
                if delta <= 0:
                    continue
                lot_size = request.lot_sizes[row][position]
                adjusted[instrument] = float(
                    int((delta * scale) / lot_size + 1e-12) * lot_size
                )
            deltas = adjusted
    return {
        instrument: float(current.get(instrument, 0.0)) + float(deltas.get(instrument, 0.0))
        for instrument in request.instruments
    }
