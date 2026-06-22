"""Native event-runtime runner for raw group strategy inputs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from ...event_driven.backtest import BacktestRunner, ExecutionVenue, StrategyLane
from ...event_driven.contracts import BacktestPlan, RunIdentity
from ...event_driven.runtime import EventTopic, MarketSlice, ProductPrice, ReplayEventSource
from ...execution.fees import ProviderCommissionModel
from ...execution.trading import (
    CashAccounting,
    Ledger,
    MarketState,
    NextBarBroker,
    OrderManager,
    ProviderContractSizer,
)
from ...factors.events import PrecomputedFactorPublisher
from ...market_rules import (
    ContractRule,
    FeeSchedule,
    RuleFallbackPolicy,
    RuleUsageJournal,
    TemporalRuleProvider,
)
from ...risk.margin import FuturesMarginConstraint
from ...strategies.membership import MembershipAllocationStrategy
from .common import market_rule_diagnostics, parse_target_weight_input


def run_group_strategy(payload: Mapping[str, Any], progress=None) -> dict[str, Any]:
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
                name: ProductPrice(
                    name,
                    adjusted[row, column],
                    (
                        {"VOLUME": request.volumes[name][row]}
                        if request.volumes is not None else {}
                    ),
                )
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
    rule_usages: dict[str, RuleUsageJournal] = {}
    if payload.get("signal_updates") is None:
        raise ValueError("native group strategy requires an explicit signal-update mask")
    signal_updates = np.asarray(payload["signal_updates"], dtype=bool)
    if signal_updates.shape != membership.shape[:2]:
        raise ValueError("signal-update mask must match membership time/strategy axes")
    for position, config in enumerate(strategy_configs):
        strategy_id = str(config["strategy_id"])
        portfolio_id = f"{strategy_id}:portfolio"
        factor_alias = f"membership:{strategy_id}"
        if str(config.get("strategy_kind") or "group") == "long_short":
            long_indices = tuple(int(value) for value in config.get("long_indices", ()))
            short_indices = tuple(int(value) for value in config.get("short_indices", ()))
            factor_values = (
                np.any(membership[:, long_indices, :], axis=1).astype(float)
                - np.any(membership[:, short_indices, :], axis=1).astype(float)
            )
            active_mask = np.any(
                signal_updates[:, long_indices + short_indices], axis=1
            )
        else:
            membership_index = int(config.get("membership_index", position))
            factor_values = membership[:, membership_index, :].astype(float)
            active_mask = signal_updates[:, membership_index]
        factors.append(PrecomputedFactorPublisher(
            factor_alias,
            pd.DataFrame(
                factor_values,
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
                if active_mask[row]
            ),
        )
        ledger = Ledger(
            portfolio_id,
            request.instruments,
            round(float(config.get("initial_capital") or request.initial_cash) * 100),
            CashAccounting(point_values={name: 1.0 for name in request.instruments}),
            valuation_prices=market.prices,
        )
        usage = RuleUsageJournal()
        rule_usages[strategy_id] = usage
        contract_history = {
            name: [
                (
                    timestamp,
                    ContractRule(1.0, request.lot_sizes[row][column], 1e-12),
                )
                for row, timestamp in enumerate(request.timestamps)
            ]
            for column, name in enumerate(request.instruments)
        }
        sizer = ProviderContractSizer(
            market,
            TemporalRuleProvider(contract_history),
            RuleFallbackPolicy.STRICT_HISTORICAL,
            usage,
        )
        intent_policy = None
        if str(config.get("margin_mode") or "none") != "none":
            margin_history = {
                name: [
                    (timestamp, request.margin_ratios[row][column])
                    for row, timestamp in enumerate(request.timestamps)
                ]
                for column, name in enumerate(request.instruments)
            }
            intent_policy = FuturesMarginConstraint(
                ledger,
                TemporalRuleProvider(margin_history),
                RuleFallbackPolicy.STRICT_HISTORICAL,
                usage,
                collateral_fraction=float(config.get("collateral_fraction") or 1.0),
                reject_instead_of_scale=str(config.get("margin_mode")) == "reject",
            ).on_portfolio_intent
        lanes.append(StrategyLane(
            strategy,
            ledger,
            OrderManager(ledger, sizer),
            intent_policy=intent_policy,
        ))
        fee_rate = float(config.get("fee_rate") or 0.0)
        fee_history = {
            name: [(timestamp, FeeSchedule(notional_rate=fee_rate))]
            for name in request.instruments
            for timestamp in request.timestamps[:1]
        }
        def _fill_price(order, quote, quantity, config=config):
            mode = str(config.get("slippage_mode") or "none")
            if mode == "none":
                return quote.price
            if mode == "fixed_bps":
                bps = float(config.get("slippage_bps") or 0.0)
                direction = 1.0 if order.side.value == "buy" else -1.0
                return quote.price * (1.0 + direction * bps / 10_000.0)
            raise ValueError(f"unsupported slippage mode: {mode}")

        def _capacity(order, quote, config=config):
            mode = str(config.get("liquidity_mode") or "infinite")
            if mode == "infinite":
                return float("inf")
            if mode == "volume_participation":
                return float(quote.fields["VOLUME"]) * float(
                    config.get("participation_rate") or 0.0
                )
            raise ValueError(f"unsupported liquidity mode: {mode}")

        broker = NextBarBroker(
            {portfolio_id},
            commission_model=ProviderCommissionModel(
                TemporalRuleProvider(fee_history),
                RuleFallbackPolicy.STRICT_HISTORICAL,
                usage,
            ),
            capacity=_capacity,
            fill_price=_fill_price,
        )
        venues.append(ExecutionVenue(
            frozenset({portfolio_id}),
            broker.on_order_submitted,
            on_market_slice=broker.on_market_slice,
        ))
        strategies.append(strategy)
    result = BacktestRunner(
        BacktestPlan(RunIdentity(str(payload.get("run_id") or "native-group")), pd.DatetimeIndex(request.timestamps), request.instruments),
        market_source=source,
        market=market,
        factors=tuple(factors),
        lanes=tuple(lanes),
        venues=tuple(venues),
        progress=(
            lambda item: progress(
                item.completed,
                item.total,
                request.timestamps[min(item.completed, len(request.timestamps)) - 1],
            )
            if progress is not None and item.phase == "event_replay" and item.completed
            else None
        ),
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
            "position_curve": {
                snapshot.timestamp.isoformat(): dict(snapshot.positions)
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
            strategy.strategy_id: {
                **strategy.diagnostics,
                **market_rule_diagnostics(payload),
                "runtime_rule_approximation_count": rule_usages[
                    strategy.strategy_id
                ].approximation_count,
            }
            for strategy in strategies
        },
        "event_count": result.event_count,
    }
