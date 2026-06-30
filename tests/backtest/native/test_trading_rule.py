from __future__ import annotations

import uuid

import pytest

from tools.products.Product import Product
from tools.testers.backtest.engines.native.ledger import Ledger, Lot, ProductPosition, StrategyConfig
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.trading_rule import (
    TradingRuleModule, _resolve_method, _resolve_use_int_position, close_position, open_position,
)
from tools.testers.backtest.modules.margin import (
    MarginModule, _resolve_margin_mode, _resolve_margin_ratio,
)


def _product(margin_traded: bool = False) -> Product:
    return Product(name=f"P-{uuid.uuid4().hex}", point_value=1, currency="CNY", is_margin_traded=margin_traded)


def _config(**values) -> StrategyConfig:
    s = Strategy(alias="S")
    field_values = {}
    for key, value in values.items():
        ref = getattr(TradingRuleModule, key, None) or getattr(MarginModule, key)
        field_values[ref] = value
    return StrategyConfig(strategy=s, field_values=field_values)


def test_resolve_method_basic_is_always_weight_average():
    config = _config(accounting_mode="Basic")
    assert _resolve_method(config, _product()) == "WeightAverage"


def test_resolve_method_custom_reads_field():
    config = _config(accounting_mode="Custom", cost_basis_method="FIFO")
    assert _resolve_method(config, _product()) == "FIFO"


def test_resolve_method_auto_margin_traded_is_daily_mark_to_market():
    config = _config(accounting_mode="Auto")
    assert _resolve_method(config, _product(margin_traded=True)) == "DailyMarkToMarket"


def test_resolve_method_auto_non_margin_falls_back_to_fifo():
    config = _config(accounting_mode="Auto")
    assert _resolve_method(config, _product(margin_traded=False)) == "FIFO"


def test_resolve_use_int_position_basic_false_auto_true_custom_reads_field():
    assert _resolve_use_int_position(_config(accounting_mode="Basic")) is False
    assert _resolve_use_int_position(_config(accounting_mode="Auto")) is True
    assert _resolve_use_int_position(_config(accounting_mode="Custom", use_int_position=True)) is True
    assert _resolve_use_int_position(_config(accounting_mode="Custom")) is False


def test_resolve_margin_mode_defaults_auto_and_reads_field():
    assert _resolve_margin_mode(_config(accounting_mode="Basic")) == "none"
    assert _resolve_margin_mode(_config(accounting_mode="Auto")) == "auto"
    assert _resolve_margin_mode(_config(accounting_mode="Custom", margin_mode="fixed")) == "fixed"


def test_resolve_margin_ratio_basic_is_zero():
    config = _config(accounting_mode="Basic")
    assert _resolve_margin_ratio(config, market_margin_ratio=0.1) == 0.0


def test_resolve_margin_ratio_none_is_zero():
    config = _config(accounting_mode="Custom", margin_mode="none")
    assert _resolve_margin_ratio(config, market_margin_ratio=0.1) == 0.0


def test_resolve_margin_ratio_fixed_uses_fixed_field():
    config = _config(accounting_mode="Custom", margin_mode="fixed", fixed_margin_ratio=0.2)
    assert _resolve_margin_ratio(config, market_margin_ratio=0.9) == 0.2


def test_resolve_margin_ratio_auto_uses_caller_supplied_market_ratio():
    config = _config(accounting_mode="Auto")
    assert _resolve_margin_ratio(config, market_margin_ratio=0.15) == 0.15


def test_equity_occupied_basic_accounting_has_zero_margin():
    product = _product()
    config = _config(accounting_mode="Basic")
    ledger = Ledger(strategy=config.strategy, base_currency="CNY")
    ledger.set(_positions_ref(), {product: ProductPosition(quantity=0.0, average_cost=0.0,
                                                              equity_occupied=None)})
    open_position(ledger, config, product, quantity=10.0, entry_price=5.0, multiplier=1.0)
    entry = ledger.get(_positions_ref())[product]
    assert entry.equity_occupied.to_major() == pytest.approx(0.0)


def test_equity_occupied_fixed_margin_ratio_discounts_notional():
    product = _product()
    config = _config(accounting_mode="Custom", cost_basis_method="WeightAverage",
                     margin_mode="fixed", fixed_margin_ratio=0.1)
    ledger = Ledger(strategy=config.strategy, base_currency="CNY")
    ledger.set(_positions_ref(), {product: ProductPosition(quantity=0.0, average_cost=0.0)})
    open_position(ledger, config, product, quantity=10.0, entry_price=5.0, multiplier=1.0)
    entry = ledger.get(_positions_ref())[product]
    assert entry.equity_occupied.to_major() == pytest.approx(5.0)  # 10*5*1*0.1


def test_weight_average_open_then_partial_close_realizes_pnl_at_average_cost():
    product = _product()
    config = _config(accounting_mode="Basic")
    ledger = Ledger(strategy=config.strategy, base_currency="CNY")
    ledger.set(_positions_ref(), {product: ProductPosition(quantity=0.0, average_cost=0.0)})

    open_position(ledger, config, product, quantity=10.0, entry_price=10.0, multiplier=1.0)
    open_position(ledger, config, product, quantity=10.0, entry_price=20.0, multiplier=1.0)
    entry = ledger.get(_positions_ref())[product]
    assert entry.quantity == 20.0
    assert entry.average_cost == pytest.approx(15.0)

    realized = close_position(ledger, config, product, quantity=5.0, fill_price=18.0, multiplier=1.0)
    assert realized.to_major() == pytest.approx(5.0 * (18.0 - 15.0))
    entry = ledger.get(_positions_ref())[product]
    assert entry.quantity == 15.0


def test_fifo_closes_earliest_lot_first():
    product = _product()
    config = _config(accounting_mode="Custom", cost_basis_method="FIFO")
    ledger = Ledger(strategy=config.strategy, base_currency="CNY")
    from collections import deque
    ledger.set(_positions_ref(), {product: ProductPosition(quantity=0.0, lots=deque())})

    open_position(ledger, config, product, quantity=10.0, entry_price=10.0, multiplier=1.0)
    open_position(ledger, config, product, quantity=10.0, entry_price=20.0, multiplier=1.0)

    realized = close_position(ledger, config, product, quantity=10.0, fill_price=25.0, multiplier=1.0)
    # FIFO closes the first lot (entry_price=10) first
    assert realized.to_major() == pytest.approx(10.0 * (25.0 - 10.0))
    entry = ledger.get(_positions_ref())[product]
    assert entry.quantity == 10.0
    assert len(entry.lots) == 1
    assert entry.lots[0].entry_price == 20.0


def test_lifo_closes_latest_lot_first():
    product = _product()
    config = _config(accounting_mode="Custom", cost_basis_method="LIFO")
    ledger = Ledger(strategy=config.strategy, base_currency="CNY")
    from collections import deque
    ledger.set(_positions_ref(), {product: ProductPosition(quantity=0.0, lots=deque())})

    open_position(ledger, config, product, quantity=10.0, entry_price=10.0, multiplier=1.0)
    open_position(ledger, config, product, quantity=10.0, entry_price=20.0, multiplier=1.0)

    realized = close_position(ledger, config, product, quantity=10.0, fill_price=25.0, multiplier=1.0)
    assert realized.to_major() == pytest.approx(10.0 * (25.0 - 20.0))
    entry = ledger.get(_positions_ref())[product]
    assert entry.lots[0].entry_price == 10.0


def test_hifo_closes_highest_cost_lot_first():
    product = _product()
    config = _config(accounting_mode="Custom", cost_basis_method="HIFO")
    ledger = Ledger(strategy=config.strategy, base_currency="CNY")
    from collections import deque
    ledger.set(_positions_ref(), {product: ProductPosition(quantity=0.0, lots=deque())})

    open_position(ledger, config, product, quantity=10.0, entry_price=10.0, multiplier=1.0)
    open_position(ledger, config, product, quantity=10.0, entry_price=30.0, multiplier=1.0)  # highest cost, middle in time
    open_position(ledger, config, product, quantity=10.0, entry_price=20.0, multiplier=1.0)

    realized = close_position(ledger, config, product, quantity=10.0, fill_price=35.0, multiplier=1.0)
    assert realized.to_major() == pytest.approx(10.0 * (35.0 - 30.0))
    remaining_costs = sorted(lot.entry_price for lot in ledger.get(_positions_ref())[product].lots)
    assert remaining_costs == [10.0, 20.0]


def _positions_ref():
    from tools.testers.backtest.modules.ledger_module import LedgerModule
    return LedgerModule.positions
