"""Native event-runtime runner for raw group strategy inputs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from ...event_driven.backtest import BacktestRunner, ExecutionVenue, StrategyLane
from ...event_driven.contracts import BacktestPlan, RunIdentity
from ...event_driven.runtime import EventTopic, MarketSlice, ProductPrice, ReplayEventSource
from ...execution.trading import CashAccounting, ImmediateBroker, Ledger, MarketState, OrderManager
from ...factors.events import PrecomputedFactorPublisher
from ...strategies.membership import MembershipAllocationStrategy
from .common import parse_target_weight_input


def run_group_strategy(payload: Mapping[str, Any]) -> dict[str, Any]:
    strategy_configs = tuple(payload.get("strategy_configs", ()))
    request = parse_target_weight_input({
        **dict(payload),
        "strategies": [
            {"strategy_id": str(config.get("strategy_id") or ""), "targets": {}}
            for config in strategy_configs
        ],
    })
    membership = np.asarray(payload.get("membership"), dtype=bool)
    market = MarketState()
    adjusted = np.asarray([
        [
            request.prices[name][row] * request.multipliers[row][column]
            for column, name in enumerate(request.instruments)
        ]
        for row in range(len(request.timestamps))
    ])
    source = ReplayEventSource(
        request.timestamps,
        [
            MarketSlice({
                name: ProductPrice(name, adjusted[row, column])
                for column, name in enumerate(request.instruments)
            })
            for row in range(len(request.timestamps))
        ],
        topic=EventTopic.MARKET_SLICE_CLOSED,
    )
    margin_by_timestamp = {
        timestamp: dict(zip(request.instruments, row, strict=True))
        for timestamp, row in zip(
            request.timestamps,
            request.margin_ratios,
            strict=True,
        )
    }
    factors = []
    lanes = []
    venues = []
    strategies = []
    if payload.get("signal_updates") is None:
        raise ValueError("native group strategy requires an explicit signal-update mask")
    signal_updates = np.asarray(payload["signal_updates"], dtype=bool)
    if signal_updates.shape != membership.shape[:2]:
        raise ValueError("signal-update mask must match membership time/strategy axes")
    for position, config in enumerate(strategy_configs):
        strategy_id = str(config["strategy_id"])
        portfolio_id = f"{strategy_id}:portfolio"
        factor_alias = f"membership:{strategy_id}"
        factors.append(PrecomputedFactorPublisher(
            factor_alias,
            pd.DataFrame(
                membership[:, position, :].astype(float),
                index=request.timestamps,
                columns=request.instruments,
            ),
        ))
        strategy = MembershipAllocationStrategy(
            factor_alias=factor_alias,
            strategy_id=strategy_id,
            portfolio_id=portfolio_id,
            instruments=request.instruments,
            market=market,
            config=config,
            margin_ratios=margin_by_timestamp,
            active_timestamps=frozenset(
                timestamp
                for row, timestamp in enumerate(request.timestamps)
                if signal_updates[row, position]
            ),
        )
        ledger = Ledger(
            portfolio_id,
            request.instruments,
            round(float(config.get("initial_capital") or request.initial_cash) * 100),
            CashAccounting(point_values={name: 1.0 for name in request.instruments}),
        )
        from ...execution.trading import EqualNotionalSizer
        lot_sizes = {
            name: request.lot_sizes[0][column]
            for column, name in enumerate(request.instruments)
        }
        sizer = EqualNotionalSizer(
            market,
            {name: 1.0 for name in request.instruments},
            lot_sizes,
        )
        lanes.append(StrategyLane(strategy, ledger, OrderManager(ledger, sizer)))
        broker = ImmediateBroker(market)
        venues.append(ExecutionVenue(frozenset({portfolio_id}), broker.on_order_submitted))
        strategies.append(strategy)
    result = BacktestRunner(
        BacktestPlan(RunIdentity(str(payload.get("run_id") or "native-group")), pd.DatetimeIndex(request.timestamps), request.instruments),
        market_source=source,
        market=market,
        factors=tuple(factors),
        lanes=tuple(lanes),
        venues=tuple(venues),
    ).run()
    portfolios = {
        portfolio.strategy_id: {
            "initial_value": portfolio.snapshots[0].equity_minor / 100.0 if portfolio.snapshots else request.initial_cash,
            "final_value": portfolio.final_snapshot.equity_minor / 100.0,
            "positions": dict(portfolio.final_snapshot.positions),
            "equity_curve": {
                snapshot.timestamp.isoformat(): snapshot.equity_minor / 100.0
                for snapshot in portfolio.snapshots
            },
        }
        for portfolio in result.portfolios.values()
    }
    return {
        "engine": "native",
        "portfolios": portfolios,
        "target_trace": {strategy.strategy_id: strategy.target_trace for strategy in strategies},
        "strategy_diagnostics": {
            strategy.strategy_id: strategy.diagnostics for strategy in strategies
        },
        "event_count": result.event_count,
    }
