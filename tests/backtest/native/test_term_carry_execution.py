from __future__ import annotations

from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.modules.ledger_module import (
    LedgerModule,
    _apply_order_fill,
    _initialize_ledgers,
)
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.order_construct import (
    OrderConstructModule,
    _basic_size_order,
    _construct_orders,
)
from tools.testers.backtest.modules.product_selection import ProductSelectionModule
from tools.testers.backtest.modules.target import TargetStrategyModule

from .term_carry_strategy_support import term_carry_state, term_carry_target


def _fill_constructed_orders(state, strategy, ctx):
    orders = ctx.get_for(OrderConstructModule.orders, strategy)
    fill_ctx = FlowContext(
        timestamp=ctx.timestamp,
        event_queue=EventQueue(),
        active_strategies=frozenset({strategy}),
        drafts_by_strategy={
            strategy: [
            EventDraft(EventKind.ORDER, ctx.timestamp, strategy, order)
            for order in orders
            ],
        },
    )
    fill_ctx.set(
        MarketDataModule.current_prices,
        ctx.get(MarketDataModule.current_prices),
    )
    fill_ctx.set(MarketDataModule.current_historical_fields, {})
    _apply_order_fill(state, fill_ctx)
    return orders


def _size_construct_fill(state, strategy, near, far, ctx):
    ctx.set_for(LedgerModule.equity, strategy, 100_000.0)
    ctx.set(MarketDataModule.current_prices, {near: 100.0, far: 80.0})
    _basic_size_order(state, ctx)
    raw = ctx.get_for(OrderConstructModule.raw_deltas, strategy)
    ctx.set_for(OrderConstructModule.deltas, strategy, raw)
    ctx.set(MarketDataModule.current_historical_fields, {})
    _construct_orders(state, ctx)
    return _fill_constructed_orders(state, strategy, ctx)


def test_term_carry_target_opens_and_closes_both_ledger_legs():
    state, strategy, product, near, far = term_carry_state()
    init = term_carry_target(
        state, strategy, product, near, far, "2025-01-01", 0.0,
    )
    init.set_for(ProductSelectionModule.products, strategy, {near, far})
    _initialize_ledgers(state, init)

    opening = term_carry_target(
        state, strategy, product, near, far, "2025-01-02", 0.08,
        prices={near: 100.0, far: 80.0},
    )
    open_orders = _size_construct_fill(
        state, strategy, near, far, opening,
    )
    positions = state.ledger_for_strategy(strategy).get(LedgerModule.positions)
    assert positions[near].quantity == 500.0
    assert positions[far].quantity == -625.0
    assert len({order.parent_intent_id for order in open_orders}) == 1

    exiting = term_carry_target(
        state, strategy, product, near, far, "2025-01-03", 0.0,
        prices={near: 100.0, far: 80.0},
    )
    assert exiting.get_for(TargetStrategyModule.target_weights, strategy) == {}
    close_orders = _size_construct_fill(
        state, strategy, near, far, exiting,
    )

    assert positions[near].quantity == 0
    assert positions[far].quantity == 0
    assert len({order.parent_intent_id for order in close_orders}) == 1
    assert (
        open_orders[0].parent_intent_id
        != close_orders[0].parent_intent_id
    )
