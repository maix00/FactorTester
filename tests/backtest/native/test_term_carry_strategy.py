from __future__ import annotations

import pytest

from tools.testers.backtest.engines.native.order import OrderSide
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.modules.term_carry import TermCarryStrategyModule
from tools.testers.backtest.modules.ledger_module import (
    _initialize_ledgers,
)
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.group_membership import GroupMembershipModule
from tools.testers.backtest.modules.order_construct import (
    OrderConstructModule,
    _construct_orders,
)
from tools.testers.backtest.modules.product_selection import ProductSelectionModule
from tools.testers.backtest.modules.target import (
    PairedTargetWeightIntent,
    TargetStrategyModule,
)
from tools.testers.backtest.modules.term_structure import (
    _resolve_tradable_target_weights,
)

from .term_carry_strategy_support import term_carry_state, term_carry_target


def test_term_carry_state_machine_opens_both_directions_and_exits_together():
    state, strategy, product, near, far = term_carry_state()

    positive = term_carry_target(
        state, strategy, product, near, far, "2025-01-02", 0.08,
    )
    assert positive.get_for(TargetStrategyModule.target_weights, strategy) == {
        near: pytest.approx(0.5),
        far: pytest.approx(-0.5),
    }
    negative = term_carry_target(
        state, strategy, product, near, far, "2025-01-03", -0.08,
    )
    assert negative.get_for(TargetStrategyModule.target_weights, strategy) == {
        near: pytest.approx(-0.5),
        far: pytest.approx(0.5),
    }
    exit_ctx = term_carry_target(
        state, strategy, product, near, far, "2025-01-04", 0.0,
    )
    assert exit_ctx.get_for(TargetStrategyModule.target_weights, strategy) == {}


def test_term_carry_missing_leg_market_cannot_open_one_leg():
    state, strategy, product, near, far = term_carry_state()
    ctx = term_carry_target(
        state, strategy, product, near, far, "2025-01-02", 0.08,
        prices={near: 100.0},
    )
    assert ctx.get_for(TargetStrategyModule.target_weights, strategy) == {}
    diagnostics = ctx.get_for(
        TermCarryStrategyModule.term_carry_diagnostics, strategy,
    )
    assert diagnostics["blocked"][str(product)] == "missing_leg_market"


def test_term_carry_fixed_product_mask_excludes_other_signal_products():
    state, strategy, product, near, far = term_carry_state()
    state.config_for(strategy).field_values[
        GroupMembershipModule.product_mask_names
    ] = ("OTHER.PRODUCT",)

    ctx = term_carry_target(
        state, strategy, product, near, far, "2025-01-02", 0.08,
    )

    assert ctx.get_for(TargetStrategyModule.target_weights, strategy) == {}
    diagnostics = ctx.get_for(
        TermCarryStrategyModule.term_carry_diagnostics, strategy,
    )
    assert diagnostics["directions"] == {}


def test_term_carry_rejects_overlapping_contract_ranks():
    state, strategy, product, near, far = term_carry_state()
    state.config_for(strategy).field_values[
        TermCarryStrategyModule.term_carry_far_rank
    ] = 0

    with pytest.raises(ValueError, match="near_rank < far_rank"):
        term_carry_target(
            state, strategy, product, near, far, "2025-01-02", 0.08,
        )


def test_term_carry_orders_share_parent_intent_identity():
    state, strategy, product, near, far = term_carry_state()
    init = FlowContext(timestamp=None, event_queue=EventQueue())
    init.set_for(ProductSelectionModule.products, strategy, {near, far})
    _initialize_ledgers(state, init)
    target_ctx = term_carry_target(
        state, strategy, product, near, far, "2025-01-02", 0.08,
    )
    intent = target_ctx.get_for(TargetStrategyModule.trade_intent, strategy)
    assert isinstance(intent, PairedTargetWeightIntent)

    target_ctx.set_for(
        OrderConstructModule.deltas,
        strategy,
        {near: -2.0, far: 2.0},
    )
    target_ctx.set(MarketDataModule.current_historical_fields, {})
    _construct_orders(state, target_ctx)
    orders = target_ctx.get_for(OrderConstructModule.orders, strategy)
    assert {order.parent_intent_id for order in orders} == {
        intent.parent_intent_id
    }
    assert {order.side for order in orders} == {OrderSide.BUY, OrderSide.SELL}


def test_term_resolution_preserves_concrete_term_carry_legs_and_pair_identity():
    state, strategy, product, near, far = term_carry_state()
    ctx = term_carry_target(
        state, strategy, product, near, far, "2025-01-02", 0.08,
    )
    state.term_structure_store.contract_metadata[strategy] = (
        {"product": product.name, "contract_object": near},
        {"product": product.name, "contract_object": far},
    )
    original = ctx.get_for(TargetStrategyModule.trade_intent, strategy)

    _resolve_tradable_target_weights(state, ctx)

    assert ctx.get_for(TargetStrategyModule.target_weights, strategy) == {
        near: pytest.approx(0.5),
        far: pytest.approx(-0.5),
    }
    resolved = ctx.get_for(TargetStrategyModule.trade_intent, strategy)
    assert isinstance(resolved, PairedTargetWeightIntent)
    assert resolved.parent_intent_id == original.parent_intent_id
