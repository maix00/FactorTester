"""Flow declarations for LedgerModule."""

from __future__ import annotations

from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.minor_unit import MinorUnitModule
from tools.testers.backtest.modules.product_selection import ProductSelectionModule
from tools.testers.backtest.modules.strategy_book import StrategyBookModule

from .initialization import initialize_ledgers
from .order_fill import apply_order_fill
from .valuation import basic_equity


def build_ledger_flows(module):
    initialize = Flow(
        "initialize_ledgers",
        inputs=(
            module._engine_mode_ref, module._accounting_mode_ref,
            module._cost_basis_method_ref, module._daily_mark_to_market_enabled_ref,
            module._use_int_position_ref, MinorUnitModule.use_minor_units,
            module.initial_capital_major, module.base_currency, module.account_currency,
            ProductSelectionModule.products, StrategyBookModule.strategy_book_mode,
            module._margin_mode_ref,
        ),
        outputs=(
            module.cash, module.positions, module._margin_requirement_ref,
            module._margin_reserved_ref, module._margin_deficit_ref,
            module._margin_excess_ref, module._margin_utilization_ref,
            module._margin_limit_excess_ref,
        ),
        phase=Phase.PRE_REPLAY, order=41, owner=module.__name__,
        after=(MarketDataModule.load_raw_market_data,),
        description="初始化交易账本", compute=initialize_ledgers,
    )
    equity_signal = Flow(
        "equity_on_signal",
        inputs=equity_inputs(module), outputs=(module.equity,),
        phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL,
        description="计算信号时点权益", order=10, owner=module.__name__,
        compute=basic_equity,
    )
    fill = Flow(
        "apply_order_fill",
        inputs=(
            MarketDataModule.current_prices, MarketDataModule.current_historical_fields,
            module._engine_mode_ref, module._accounting_mode_ref,
            module._cost_basis_method_ref, module._use_int_position_ref,
            module._quantity_rounding_policy_ref, module._fee_mode_ref,
            module._fixed_fee_rate_ref, module._margin_mode_ref,
            module._fixed_margin_ratio_ref,
        ),
        outputs=(
            module.positions, module.cash, module._margin_reserved_ref,
            module._margin_deficit_ref, module._margin_excess_ref,
            module._order_fill_valuation_prices_ref, module.position_events,
            module.order_status_events,
        ),
        phase=Phase.PER_EVENT, event_kind=EventKind.ORDER, order=11,
        description="成交落账", event_payload_inputs=("order",),
        owner=module.__name__, compute=apply_order_fill,
    )
    equity_order = Flow(
        "equity_on_order",
        inputs=equity_inputs(module), outputs=(module.equity,),
        phase=Phase.PER_EVENT, event_kind=EventKind.ORDER,
        description="计算订单后权益", order=900, after=(fill,),
        owner=module.__name__, compute=basic_equity,
    )
    return initialize, equity_signal, fill, equity_order


def equity_inputs(module):
    return (
        MarketDataModule.current_prices, MarketDataModule.current_historical_fields,
        module.cash, module.positions, module._engine_mode_ref,
        module._accounting_mode_ref, module._cost_basis_method_ref,
        module._daily_mark_to_market_enabled_ref,
        module._order_fill_valuation_prices_ref,
    )
