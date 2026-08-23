"""Ledger field schema, flows, and compatibility exports."""

from __future__ import annotations

from typing import Any, ClassVar

from tools.testers.backtest.engines.native.fields import (
    ExecutableModule,
    FieldDefinition,
    FieldRef,
)
from tools.testers.backtest.modules.cash_pool import CashPoolModule
from tools.testers.backtest.modules.ledger_impl.balances import (
    margin_reserved_major as _margin_reserved_major,
    normalise_fill_quantity as _normalise_fill_quantity,
    required_cash_for_ledger as _required_cash_for_ledger,
    sync_ledger_margin_reserved as _sync_ledger_margin_reserved,
    uses_margin_accounting as _uses_margin_accounting,
)
from tools.testers.backtest.modules.ledger_impl.cash_accounting import (
    apply_cash_accounting_position_fill as _apply_cash_accounting_position_fill,
)
from tools.testers.backtest.modules.ledger_impl.cost_basis import (
    apply_lot_fill as _apply_lot_fill,
    same_direction as _same_direction,
    sign as _sign,
    weighted_average_cost as _weighted_average_cost,
)
from tools.testers.backtest.modules.ledger_impl.initialization import (
    initialize_ledgers as _initialize_ledgers,
    products_for_backtest_window as _products_for_backtest_window,
    require_matching_cash_pool_config as _require_matching_cash_pool_config,
)
from tools.testers.backtest.modules.ledger_impl.flows import build_ledger_flows
from tools.testers.backtest.modules.ledger_impl.margin_accounting import (
    apply_margin_accounting_fill as _apply_margin_accounting_fill,
)
from tools.testers.backtest.modules.ledger_impl.margin_ratios import (
    entry_margin_major as _entry_margin_major,
    market_margin_ratio as _market_margin_ratio,
    number_or_none as _number_or_none,
    resolved_margin_ratio_for_order as _resolved_margin_ratio_for_order,
    resolved_margin_ratio_for_position_after_fill as _resolved_margin_ratio_for_position_after_fill,
)
from tools.testers.backtest.modules.ledger_impl.order_fill import (
    apply_order_fill as _apply_order_fill,
)
from tools.testers.backtest.modules.ledger_impl.valuation import (
    basic_equity as _basic_equity_impl,
    ledger_equity as _ledger_equity,
    required_current_price as _required_current_price,
    valuation_prices_for_equity as _valuation_prices_for_equity,
)
from tools.testers.backtest.modules.trading_rule import _resolve_method


def _basic_equity(state, ctx) -> None:
    _basic_equity_impl(state, ctx, equity_fn=_ledger_equity)


class LedgerModule(ExecutableModule):
    key: ClassVar[str] = "portfolio_capital"
    label: ClassVar[str] = "账本"

    cash: ClassVar[FieldRef[Any]] = CashPoolModule.cash
    account_currency: ClassVar[FieldRef[str]] = FieldRef("account_currency")
    positions: ClassVar[FieldRef[Any]] = FieldRef("positions")
    equity: ClassVar[FieldRef[float]] = FieldRef("equity")
    initial_capital_major = CashPoolModule.initial_capital_major
    base_currency = CashPoolModule.base_currency
    currency_conversion_fee_rate = CashPoolModule.currency_conversion_fee_rate
    _fee_mode_ref = FieldRef("fee_mode", owner="FeeModule")
    _fixed_fee_rate_ref = FieldRef("fixed_fee_rate", owner="FeeModule")
    _quantity_rounding_policy_ref = FieldRef("quantity_rounding_policy", owner="OrderConstructModule")
    _engine_mode_ref = FieldRef("engine_mode", owner="EngineModule")
    _accounting_mode_ref = FieldRef("accounting_mode", owner="TradingRuleModule")
    _cost_basis_method_ref = FieldRef("cost_basis_method", owner="TradingRuleModule")
    _daily_mark_to_market_enabled_ref = FieldRef("daily_mark_to_market_enabled", owner="TradingRuleModule")
    _use_int_position_ref = FieldRef("use_int_position", owner="TradingRuleModule")
    _margin_mode_ref = FieldRef("margin_mode", owner="MarginModule")
    _fixed_margin_ratio_ref = FieldRef("fixed_margin_ratio", owner="MarginModule")
    _margin_requirement_ref = FieldRef("margin_requirement", owner="MarginModule")
    _margin_reserved_ref = FieldRef("margin_reserved", owner="MarginModule")
    _margin_deficit_ref = FieldRef("margin_deficit", owner="MarginModule")
    _margin_excess_ref = FieldRef("margin_excess", owner="MarginModule")
    _margin_utilization_ref = FieldRef("margin_utilization", owner="MarginModule")
    _margin_limit_excess_ref = FieldRef("margin_limit_excess", owner="MarginModule")
    _order_fill_valuation_prices_ref = FieldRef("order_fill_valuation_prices")
    position_events = FieldRef("position_events")
    order_status_events = FieldRef("order_status_events")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "account_currency": FieldDefinition(
            public=True, label="账户币种", editor="select", default="CNY", tab="capital",
            options=CashPoolModule.fields["base_currency"].options,
            chip_template="账户币种: {value}", tab_label="资金", tab_order=50,
        ),
        "positions": FieldDefinition(public=False, display_value_kind="positions"),
    }



(
    LedgerModule.initialize_ledgers,
    LedgerModule.equity_on_signal,
    LedgerModule.apply_order_fill,
    LedgerModule.equity_on_order,
) = build_ledger_flows(LedgerModule)
LedgerModule.flows = (
    LedgerModule.initialize_ledgers,
    LedgerModule.equity_on_signal,
    LedgerModule.apply_order_fill,
    LedgerModule.equity_on_order,
)
