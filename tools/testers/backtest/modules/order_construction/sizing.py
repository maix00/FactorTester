"""Translate strategy intents into target-minus-projected-position deltas."""

from __future__ import annotations

from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.market_data import (
    MarketDataModule,
    contract_multiplier_from_fields,
    is_product_tradable,
)
from tools.testers.backtest.modules.order_lifecycle import reconcile_target_delta
from tools.testers.backtest.modules.order_flow import OrderFlowModule
from tools.testers.backtest.modules.strategy_book import (
    apply_order_sizing_policy,
    ledger_for_strategy_product,
    positions_for_strategy_ledgers,
)
from tools.testers.backtest.modules.target import (
    OrderDeltaIntent,
    TargetStrategyModule,
    TargetWeightIntent,
)

from .diagnostics import record_untradable_target_skip


def basic_size_order(state, ctx, module) -> None:
    for strategy in ctx.active_strategies:
        intent = strategy_trade_intent(ctx, strategy)
        if isinstance(intent, OrderDeltaIntent):
            if hasattr(state, "ledger_for_strategy") or isinstance(
                getattr(state, "ledgers", None), dict,
            ):
                for product in intent.deltas:
                    ledger_for_strategy_product(
                        state, strategy, product, timestamp=ctx.timestamp,
                    )
            deltas = apply_order_sizing_policy(
                state, ctx, strategy, dict(intent.deltas),
            )
            ctx.set_for(module.raw_deltas, strategy, deltas)
            continue
        prices = ctx.get(MarketDataModule.current_prices)
        tradable = ctx.get(MarketDataModule.current_tradable_status, None)
        equity = ctx.get_for(LedgerModule.equity, strategy)
        fields = ctx.get_for(
            MarketDataModule.current_historical_fields, strategy,
            ctx.get(MarketDataModule.current_historical_fields, {}),
        )
        # A ledger keeps a zero-quantity ProductPosition after a contract
        # expires so that historical accounting remains inspectable.  Those
        # tombstones are not candidates for a target delta: including them in
        # this per-signal union made every later bar rescan every expired
        # contract and emit a spurious untradable warning.  Keep only a live
        # position here; a non-zero target is still retained through
        # ``target_weights`` and will be handled below.
        positions = {
            product: entry
            for product, entry in positions_for_strategy_ledgers(state, strategy).items()
            if abs(float(getattr(entry, "quantity", 0.0) or 0.0)) > 1e-12
        }
        target_weights = dict(intent.weights)
        deltas = {}
        for product in set(target_weights) | set(positions):
            target_weight = float(target_weights.get(product, 0.0) or 0.0)
            current_entry = positions.get(product)
            current_quantity = float(
                getattr(current_entry, "quantity", 0.0) or 0.0
            )
            if abs(target_weight) <= 1e-12 and abs(current_quantity) <= 1e-12:
                continue
            price = prices.get(product) if isinstance(prices, dict) else None
            if price is None or not is_product_tradable(tradable, product, prices):
                record_untradable_target_skip(
                    state, strategy, product, ctx.timestamp,
                )
                continue
            ledger = ledger_for_strategy_product(
                state, strategy, product, timestamp=ctx.timestamp,
            )
            ledger_positions = ledger.get(LedgerModule.positions, {})
            multiplier = contract_multiplier_from_fields(
                fields, product, state=state, timestamp=ctx.timestamp,
            )
            target = (
                target_weight * equity
                / (float(price) * multiplier)
            )
            actual = float(getattr(ledger_positions.get(product), "quantity", 0.0) or 0.0)
            deltas[product] = reconcile_target_delta(
                state, strategy, product, actual_quantity=actual,
                target_quantity=target, timestamp=ctx.timestamp,
                status_event_sink=lambda event: ctx.set(
                    OrderFlowModule.status_events, event,
                ),
            )
        ctx.set_for(
            module.raw_deltas, strategy,
            apply_order_sizing_policy(state, ctx, strategy, deltas),
        )


def strategy_trade_intent(ctx, strategy):
    intent = ctx.get_for(TargetStrategyModule.trade_intent, strategy, None)
    if isinstance(intent, (TargetWeightIntent, OrderDeltaIntent)):
        return intent
    weights = ctx.get_for(TargetStrategyModule.target_weights, strategy, {})
    return TargetWeightIntent(dict(weights), reason="legacy_target_weights")
