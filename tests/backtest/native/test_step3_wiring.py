"""Wires ProductSelectionModule + TermStructureExpandModule + LedgerModule +
MarketDataModule through the real scheduler (FlowRegistry.resolve +
sort_and_validate) to catch cross-module ordering bugs that per-module unit
tests can't see."""

from __future__ import annotations

from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.flow import Phase
from tools.testers.backtest.engines.native.scheduler import FlowRegistry, sort_and_validate
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.order_book import OrderBookModule
from tools.testers.backtest.modules.order_execution import OrderExecutionModule
from tools.testers.backtest.modules.order_lifecycle import OrderLifecycleModule
from tools.testers.backtest.modules.product_selection import ProductSelectionModule
from tools.testers.backtest.modules.term_structure import (
    DeliveryForceCloseModule,
    RolloverModule,
    TermStructureExpandModule,
)


def _register_all():
    registry = FlowRegistry()
    for module in (ProductSelectionModule, TermStructureExpandModule, DeliveryForceCloseModule, RolloverModule, LedgerModule,
                    MarketDataModule, OrderBookModule, OrderExecutionModule, OrderLifecycleModule):
        for flow in module.flows:
            registry.register_flow(flow)
    return registry


def test_order_group_orders_cash_update_before_equity_before_finalize():
    registry = _register_all()
    groups = sort_and_validate(registry.resolve())
    ordered_names = [f.name for f in groups[(Phase.PER_EVENT, EventKind.ORDER)]]
    assert ordered_names.index("lookup_current_prices_on_order") < ordered_names.index("cash_update")
    assert ordered_names.index("lookup_current_prices_on_order") < ordered_names.index("resolve_execution_price")
    assert ordered_names.index("resolve_execution_price") < ordered_names.index("cash_update")
    assert ordered_names.index("cash_update") < ordered_names.index("equity_on_order")
    assert ordered_names.index("equity_on_order") < ordered_names.index("finalize_order")


def test_signal_group_orders_equity_before_size_order_before_construct_orders():
    registry = _register_all()
    groups = sort_and_validate(registry.resolve())
    ordered_names = [f.name for f in groups[(Phase.PER_EVENT, EventKind.SIGNAL)]]
    assert ordered_names.index("lookup_current_prices_on_signal") < ordered_names.index("equity_on_signal")
    assert ordered_names.index("equity_on_signal") < ordered_names.index("size_order")
    assert ordered_names.index("resolve_tradable_target_weights") < ordered_names.index("size_order")
    assert ordered_names.index("size_order") < ordered_names.index("construct_orders")


def test_pre_replay_group_orders_without_error():
    registry = _register_all()
    groups = sort_and_validate(registry.resolve())
    ordered_names = [f.name for f in groups[(Phase.PRE_REPLAY, None)]]

    # resolve_product_selection (15) -> expand term-structure lifecycle/contracts
    # (20) -> check abstract+concrete-contract coverage (38) -> load_raw_market_data
    # (40) -> initialize_ledgers (41) -> causal_valuation (45).
    # expand_term_structure must run BEFORE check_market_data_coverage/
    # load_raw_market_data, not after: those two need TermStructureExpandModule.
    # expanded_contracts to plan/load each concrete contract's own price series
    # (not just the abstract product's continuous one) -- a rolled-to order
    # targets a concrete contract object and needs current_prices[that object]
    # to resolve, which only works if its price series was actually loaded.
    # Ledger initialization consumes the data-prep effective product universe,
    # so it must run after raw market data has been loaded.
    assert ordered_names.index("resolve_product_selection") < ordered_names.index("expand_term_structure")
    assert ordered_names.index("expand_term_structure") < ordered_names.index("check_market_data_coverage")
    assert ordered_names.index("expand_term_structure") < ordered_names.index("register_force_close_notices")
    assert ordered_names.index("expand_term_structure") < ordered_names.index("register_rollover_notices")
    assert ordered_names.index("expand_term_structure") < ordered_names.index("initialize_ledgers")
    assert ordered_names.index("load_raw_market_data") < ordered_names.index("initialize_ledgers")
    assert ordered_names.index("load_raw_market_data") < ordered_names.index("causal_valuation")
