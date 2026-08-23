from __future__ import annotations

import uuid
from collections import deque

import pandas as pd
import pytest

from tools.data.types.data_money import DataMoney
from tools.products.Product import Product
from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.config import LedgerConfig, StrategyConfig
from tools.testers.backtest.engines.native.position import Lot, ProductPosition
from tools.testers.backtest.engines.native.ledger import LedgerState, ledger_identity
from tools.testers.backtest.engines.native.scheduler import (
    EventQueue,
    FlowContext,
    FlowRegistry,
    make_dispatcher,
    sort_and_validate,
)
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.engine import EngineModule
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.fee import FeeModule
from tools.testers.backtest.modules.cash_pool import CashPoolModule, cash_for_ledger, set_cash_for_ledger_pool
from tools.testers.backtest.modules.strategy_book import strategy_book_store_for
from tools.testers.backtest.modules.trading_rule import (
    TradingRuleModule, _resolve_daily_mark_to_market_enabled, _resolve_daily_mark_to_market_enabled_for_ledger,
    _resolve_method, _resolve_use_int_position,
    close_position, infer_auto_cost_basis_method, mark_to_market, open_position, _apply_daily_mark_to_market,
    _register_daily_mark_to_market_notices, _settlement_price_for_product,
)
from tools.testers.backtest.modules.margin import (
    MarginModule, _apply_margin_requirement_change, _handle_margin_liquidation_notice,
    _resolve_margin_mode, _resolve_margin_ratio, product_uses_margin_accounting,
)
from tools.testers.backtest.modules.margin_risk.utilization import (
    _pool_valuation_prices,
)


def _product(margin_traded: bool = False) -> Product:
    return Product(name=f"P-{uuid.uuid4().hex}", point_value=1, currency="CNY", is_margin_traded=margin_traded)


def _config(**values) -> StrategyConfig:
    s = Strategy(alias="S")
    field_values = {}
    for key, value in values.items():
        ref = (
            getattr(EngineModule, key, None)
            or getattr(TradingRuleModule, key, None)
            or getattr(FeeModule, key, None)
            or getattr(MarginModule, key)
        )
        field_values[ref] = value
    return StrategyConfig(strategy=s, field_values=field_values)


def _ledger_config(**values) -> LedgerConfig:
    return LedgerConfig(
        fee_mode=values.get("fee_mode"),
        fixed_fee_rate=values.get("fixed_fee_rate"),
        margin_mode=values.get("margin_mode"),
        fixed_margin_ratio=values.get("fixed_margin_ratio"),
        margin_call_mode=values.get("margin_call_mode"),
        liquidation_target_buffer=values.get("liquidation_target_buffer"),
        accounting_mode=values.get("accounting_mode"),
        daily_mark_to_market_enabled=values.get("daily_mark_to_market_enabled"),
        cost_basis_method=values.get("cost_basis_method"),
        use_int_position=values.get("use_int_position"),
        cash_reserve_ratio=values.get("cash_reserve_ratio"),
        cash_reserve_major=values.get("cash_reserve_major"),
    )


def _set_cash(state: BacktestRunState, ledger: LedgerState, amount: float) -> None:
    set_cash_for_ledger_pool(state, ledger, DataMoney.from_major(
        amount, currency="CNY", use_minor_units=False))


def _cash_major(state: BacktestRunState, ledger: LedgerState) -> float:
    return cash_for_ledger(state, ledger).to_major()


def test_resolve_method_basic_is_always_weight_average():
    config = _config(engine_mode="basic")
    assert _resolve_method(config, _product()) == "WeightAverage"


def test_resolve_method_custom_reads_field():
    config = _config(engine_mode="custom")
    assert _resolve_method(config, _product(), ledger_config=_ledger_config(accounting_mode="Custom", cost_basis_method="FIFO")) == "FIFO"


def test_resolve_method_auto_uses_explicit_historical_cost_basis_method():
    config = _config(engine_mode="auto")
    assert _resolve_method(config, _product(margin_traded=True), {"CostBasisMethod": "FIFO"}) == "FIFO"


def test_resolve_method_auto_uses_fifo_and_daily_mark_to_market_when_close_today_field_exists():
    config = _config(engine_mode="auto")
    fields = {
        "CloseRatioByMoney": 0.0001,
        "CloseTodayRatioByMoney": 0.0001,
    }
    product = _product(margin_traded=False)
    assert _resolve_method(config, product, fields) == "FIFO"
    assert _resolve_daily_mark_to_market_enabled(config, product, fields) is True


def test_resolve_method_auto_uses_fifo_and_daily_mark_to_market_when_settlement_field_exists():
    config = _config(engine_mode="auto")
    product = _product(margin_traded=False)
    fields = {"SettlementPrice": 10.0}
    assert _resolve_method(config, product, fields) == "FIFO"
    assert _resolve_daily_mark_to_market_enabled(config, product, fields) is True


def test_ledger_auto_daily_mark_to_market_infers_from_historical_fields_only():
    product = _product()
    ledger_config = _ledger_config(accounting_mode="Auto")

    assert _resolve_daily_mark_to_market_enabled_for_ledger(product, {}, ledger_config=ledger_config) is False
    assert _resolve_daily_mark_to_market_enabled_for_ledger(
        product, {"SettlementPrice": 10.0}, ledger_config=ledger_config,
    ) is True


def test_ledger_margin_mode_off_disables_auto_daily_mark_to_market_even_with_exact_fee():
    product = _product()
    ledger_config = _ledger_config(accounting_mode="Auto", fee_mode="exact", margin_mode="off")

    assert _resolve_daily_mark_to_market_enabled_for_ledger(
        product,
        {"SettlementPrice": 10.0, "DailyMarkToMarketEnabled": True},
        ledger_config=ledger_config,
    ) is False


def test_ledger_auto_daily_mark_to_market_ignores_ui_default_false():
    product = _product()
    ledger_config = _ledger_config(
        accounting_mode="Auto",
        daily_mark_to_market_enabled=False,
        cost_basis_method="WeightAverage",
    )

    assert _resolve_daily_mark_to_market_enabled_for_ledger(
        product,
        {"CostBasisMethod": "DailyMarkToMarket"},
        ledger_config=ledger_config,
    ) is True


def test_apply_daily_mark_to_market_declares_real_ledger_and_cash_pool_dependencies():
    flow = TradingRuleModule.apply_daily_mark_to_market

    assert {ref.qualified_name for ref in flow.inputs} >= {
        "CashPoolModule.cash",
        "LedgerModule.positions",
        "MarketDataModule.current_market_snapshot",
        "MarketDataModule.current_historical_fields",
        "TradingRuleModule.accounting_mode",
        "TradingRuleModule.daily_mark_to_market_enabled",
        "TradingRuleModule.cost_basis_method",
        "FeeModule.fee_mode",
        "MarginModule.margin_mode",
        "MarginModule.margin_call_mode",
        "MarginModule.margin_deficit",
    }
    assert {ref.qualified_name for ref in flow.outputs} >= {
        "CashPoolModule.cash",
        "LedgerModule.positions",
        "MarginModule.margin_deficit",
        "MarginModule.margin_liquidation_orders",
    }
    assert "LedgerModule.cash" not in {ref.qualified_name for ref in flow.inputs}
    assert "LedgerModule.cash" not in {ref.qualified_name for ref in flow.outputs}


def test_ledger_custom_daily_mark_to_market_respects_explicit_switch():
    product = _product()

    assert _resolve_daily_mark_to_market_enabled_for_ledger(
        product,
        {"SettlementPrice": 10.0},
        ledger_config=_ledger_config(accounting_mode="Custom", daily_mark_to_market_enabled=False),
    ) is False
    assert _resolve_daily_mark_to_market_enabled_for_ledger(
        product,
        {},
        ledger_config=_ledger_config(
            accounting_mode="Custom",
            cost_basis_method="FIFO",
            daily_mark_to_market_enabled=True,
        ),
    ) is True


def test_ledger_custom_daily_mark_to_market_rejects_weight_average_basis():
    product = _product()

    with pytest.raises(ValueError, match="lot-based cost basis"):
        _resolve_daily_mark_to_market_enabled_for_ledger(
            product,
            {},
            ledger_config=_ledger_config(
                accounting_mode="Custom",
                cost_basis_method="WeightAverage",
                daily_mark_to_market_enabled=True,
            ),
        )


def test_resolve_method_auto_uses_fifo_when_fee_exists_without_close_today_fields():
    config = _config(engine_mode="auto")
    fields = {
        "OpenRatioByMoney": 0.0001,
        "CloseRatioByMoney": 0.0001,
    }
    assert _resolve_method(config, _product(margin_traded=False), fields) == "FIFO"


def test_legacy_daily_mark_to_market_cost_basis_field_means_fifo_plus_daily_settlement():
    config = _config(engine_mode="auto")
    product = _product(margin_traded=False)
    fields = {"CostBasisMethod": "DailyMarkToMarket"}
    assert _resolve_method(config, product, fields) == "FIFO"
    assert _resolve_daily_mark_to_market_enabled(config, product, fields) is True


def test_resolve_method_auto_without_fee_information_falls_back_to_weight_average():
    config = _config(engine_mode="auto")
    assert _resolve_method(config, _product(margin_traded=True), {}) == "WeightAverage"


def test_resolve_method_exact_requires_explicit_historical_cost_basis_method():
    config = _config(engine_mode="exact")
    with pytest.raises(KeyError):
        _resolve_method(config, _product(), {}, require_exact=True)


def test_infer_auto_cost_basis_rejects_unknown_explicit_method():
    with pytest.raises(ValueError):
        infer_auto_cost_basis_method({"CostBasisMethod": "Mystery"})


def test_resolve_use_int_position_basic_false_auto_true_custom_reads_field():
    assert _resolve_use_int_position(_config(engine_mode="basic")) is False
    assert _resolve_use_int_position(_config(engine_mode="auto")) is True
    assert _resolve_use_int_position(_config(engine_mode="custom"), _ledger_config(accounting_mode="Custom", use_int_position=True)) is True
    assert _resolve_use_int_position(_config(engine_mode="custom"), _ledger_config(accounting_mode="Custom")) is True


def test_resolve_margin_mode_defaults_auto_and_reads_field():
    assert _resolve_margin_mode(_config(engine_mode="basic")) == "none"
    assert _resolve_margin_mode(_config(engine_mode="auto")) == "auto"
    assert _resolve_margin_mode(_config(engine_mode="custom")) == "auto"
    assert _resolve_margin_mode(_config(engine_mode="custom"), _ledger_config(margin_mode="fixed")) == "fixed"


def test_resolve_margin_ratio_basic_is_zero():
    config = _config(engine_mode="basic")
    assert _resolve_margin_ratio(config, market_margin_ratio=0.1) == 0.0


def test_resolve_margin_ratio_none_is_zero():
    config = _config(engine_mode="custom", margin_mode="none")
    assert _resolve_margin_ratio(config, market_margin_ratio=0.1, ledger_config=_ledger_config(margin_mode="none")) == 0.0


def test_resolve_margin_ratio_fixed_uses_fixed_field():
    config = _config(engine_mode="custom", margin_mode="fixed", fixed_margin_ratio=0.2)
    assert _resolve_margin_ratio(config, market_margin_ratio=0.9, ledger_config=_ledger_config(margin_mode="fixed", fixed_margin_ratio=0.2)) == 0.2


def test_resolve_margin_ratio_auto_uses_caller_supplied_market_ratio():
    config = _config(engine_mode="auto")
    assert _resolve_margin_ratio(config, market_margin_ratio=0.15) == 0.15


def test_auto_margin_accounting_is_product_level_not_ledger_wide():
    ledger_config = _ledger_config(margin_mode="auto")

    assert product_uses_margin_accounting(
        {"VolumeMultiple": 10.0, "LongMarginRatioByMoney": 0.12},
        ledger_config,
    )
    assert not product_uses_margin_accounting({}, ledger_config)


def test_exact_margin_requires_rules_for_multiplier_products_only():
    ledger_config = _ledger_config(margin_mode="exact")

    assert not product_uses_margin_accounting({}, ledger_config)
    with pytest.raises(KeyError, match="exact margin mode requires"):
        product_uses_margin_accounting({"VolumeMultiple": 10.0}, ledger_config)


def test_margin_reserved_basic_accounting_has_zero_margin():
    product = _product()
    config = _config(engine_mode="basic")
    ledger = LedgerState(strategy=config.strategy, base_currency="CNY")
    ledger.set(_positions_ref(), {product: ProductPosition(quantity=0.0, average_cost=0.0,
                                                              margin_reserved=None)})
    open_position(ledger, config, product, quantity=10.0, entry_price=5.0, multiplier=1.0)
    entry = ledger.get(_positions_ref())[product]
    assert entry.margin_reserved.to_major() == pytest.approx(0.0)


def test_margin_reserved_fixed_margin_ratio_discounts_notional():
    product = _product()
    config = _config(engine_mode="custom", accounting_mode="Custom", cost_basis_method="WeightAverage",
                     margin_mode="fixed", fixed_margin_ratio=0.1)
    ledger_config = _ledger_config(accounting_mode="Custom", cost_basis_method="WeightAverage",
                                   margin_mode="fixed", fixed_margin_ratio=0.1)
    ledger = LedgerState(strategy=config.strategy, base_currency="CNY")
    ledger.set(_positions_ref(), {product: ProductPosition(quantity=0.0, average_cost=0.0)})
    open_position(ledger, config, product, quantity=10.0, entry_price=5.0, multiplier=1.0,
                  ledger_config=ledger_config)
    entry = ledger.get(_positions_ref())[product]
    assert entry.margin_reserved.to_major() == pytest.approx(5.0)  # 10*5*1*0.1


def test_weight_average_open_then_partial_close_realizes_pnl_at_average_cost():
    product = _product()
    config = _config(engine_mode="basic")
    ledger = LedgerState(strategy=config.strategy, base_currency="CNY")
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
    config = _config(engine_mode="custom", accounting_mode="Custom", cost_basis_method="FIFO")
    ledger_config = _ledger_config(accounting_mode="Custom", cost_basis_method="FIFO")
    ledger = LedgerState(strategy=config.strategy, base_currency="CNY")
    from collections import deque
    ledger.set(_positions_ref(), {product: ProductPosition(quantity=0.0, lots=deque())})

    open_position(ledger, config, product, quantity=10.0, entry_price=10.0, multiplier=1.0,
                  ledger_config=ledger_config)
    open_position(ledger, config, product, quantity=10.0, entry_price=20.0, multiplier=1.0,
                  ledger_config=ledger_config)

    realized = close_position(ledger, config, product, quantity=10.0, fill_price=25.0, multiplier=1.0,
                              ledger_config=ledger_config)
    # FIFO closes the first lot (entry_price=10) first
    assert realized.to_major() == pytest.approx(10.0 * (25.0 - 10.0))
    entry = ledger.get(_positions_ref())[product]
    assert entry.quantity == 10.0
    assert len(entry.lots) == 1
    assert entry.lots[0].entry_price == 20.0


def test_lifo_closes_latest_lot_first():
    product = _product()
    config = _config(engine_mode="custom", accounting_mode="Custom", cost_basis_method="LIFO")
    ledger_config = _ledger_config(accounting_mode="Custom", cost_basis_method="LIFO")
    ledger = LedgerState(strategy=config.strategy, base_currency="CNY")
    from collections import deque
    ledger.set(_positions_ref(), {product: ProductPosition(quantity=0.0, lots=deque())})

    open_position(ledger, config, product, quantity=10.0, entry_price=10.0, multiplier=1.0,
                  ledger_config=ledger_config)
    open_position(ledger, config, product, quantity=10.0, entry_price=20.0, multiplier=1.0,
                  ledger_config=ledger_config)

    realized = close_position(ledger, config, product, quantity=10.0, fill_price=25.0, multiplier=1.0,
                              ledger_config=ledger_config)
    assert realized.to_major() == pytest.approx(10.0 * (25.0 - 20.0))
    entry = ledger.get(_positions_ref())[product]
    assert entry.lots[0].entry_price == 10.0


def test_hifo_closes_highest_cost_lot_first():
    product = _product()
    config = _config(engine_mode="custom", accounting_mode="Custom", cost_basis_method="HIFO")
    ledger_config = _ledger_config(accounting_mode="Custom", cost_basis_method="HIFO")
    ledger = LedgerState(strategy=config.strategy, base_currency="CNY")
    from collections import deque
    ledger.set(_positions_ref(), {product: ProductPosition(quantity=0.0, lots=deque())})

    open_position(ledger, config, product, quantity=10.0, entry_price=10.0, multiplier=1.0,
                  ledger_config=ledger_config)
    open_position(ledger, config, product, quantity=10.0, entry_price=30.0, multiplier=1.0,
                  ledger_config=ledger_config)  # highest cost, middle in time
    open_position(ledger, config, product, quantity=10.0, entry_price=20.0, multiplier=1.0,
                  ledger_config=ledger_config)

    realized = close_position(ledger, config, product, quantity=10.0, fill_price=35.0, multiplier=1.0,
                              ledger_config=ledger_config)
    assert realized.to_major() == pytest.approx(10.0 * (35.0 - 30.0))
    remaining_costs = sorted(lot.entry_price for lot in ledger.get(_positions_ref())[product].lots)
    assert remaining_costs == [10.0, 20.0]


def test_daily_mark_to_market_notice_uses_trading_day_last_bar_not_calendar_day():
    strategy = Strategy(alias="S")
    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            active_flow_names=frozenset({"register_daily_mark_to_market_notices"}),
            field_values={
                EngineModule.engine_mode: "auto",
                TradingRuleModule.accounting_mode: "Auto",
            },
        )
    })
    trade_times = pd.DatetimeIndex([
        pd.Timestamp("2026-03-09 21:00:00", tz="Asia/Shanghai"),
        pd.Timestamp("2026-03-10 09:01:00", tz="Asia/Shanghai"),
        pd.Timestamp("2026-03-10 15:00:00", tz="Asia/Shanghai"),
    ])
    trading_days = pd.DatetimeIndex(["2026-03-10", "2026-03-10", "2026-03-10"])
    index = pd.MultiIndex.from_arrays([trading_days, trade_times], names=["trading_day", "_SIGNAL@MIN1"])
    account.market_data_store.current_prices_table = pd.DataFrame({"P1": [1.0, 2.0, 3.0]}, index=index)
    queue = EventQueue()
    captured = []
    queue.set_dispatcher(EventKind.LEDGER, lambda batch: captured.extend(batch))
    ctx = FlowContext(timestamp=None, event_queue=queue, active_strategies=frozenset({strategy}))

    _register_daily_mark_to_market_notices(account, ctx)
    queue.run_until_drained()

    assert len(captured) == 1
    assert captured[0].timestamp == pd.Timestamp("2026-03-10 15:00:00.000000001", tz="Asia/Shanghai")
    assert captured[0].strategy is None
    assert captured[0].ledger == ledger_identity("private:S")
    assert captured[0].payload == {
        "kind": "daily_mark_to_market",
        "trading_day": "2026-03-10",
        "ledger_id": "private:S",
    }


def test_daily_mark_to_market_notice_uses_market_close_table_not_intraday_signal_table():
    strategy = Strategy(alias="S")
    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            active_flow_names=frozenset({"register_daily_mark_to_market_notices"}),
            field_values={
                EngineModule.engine_mode: "auto",
                TradingRuleModule.accounting_mode: "Auto",
            },
        )
    })
    trading_days = pd.DatetimeIndex(["2025-12-31", "2025-12-31"])
    market_times = pd.DatetimeIndex([
        pd.Timestamp("2025-12-31 09:01:00", tz="Asia/Shanghai"),
        pd.Timestamp("2025-12-31 15:00:00", tz="Asia/Shanghai"),
    ])
    close_index = pd.MultiIndex.from_arrays([trading_days, market_times], names=["trading_day", "_SIGNAL@MIN1"])
    account.market_data_store.market_price_tables = {
        "close": pd.DataFrame({"P1": [10.0, 12.0]}, index=close_index)
    }
    signal_index = pd.MultiIndex.from_arrays(
        [trading_days[:1], market_times[:1]],
        names=["trading_day", "_SIGNAL@MIN1"],
    )
    account.market_data_store.current_prices_table = pd.DataFrame({"P1": [10.0]}, index=signal_index)
    queue = EventQueue()
    captured = []
    queue.set_dispatcher(EventKind.LEDGER, lambda batch: captured.extend(batch))
    ctx = FlowContext(timestamp=None, event_queue=queue, active_strategies=frozenset({strategy}))

    _register_daily_mark_to_market_notices(account, ctx)
    queue.run_until_drained()

    assert len(captured) == 1
    assert captured[0].timestamp == pd.Timestamp("2025-12-31 15:00:00.000000001", tz="Asia/Shanghai")


def test_daily_mark_to_market_notice_prefers_source_trading_day_event_axis():
    strategy = Strategy(alias="S")
    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            active_flow_names=frozenset({"register_daily_mark_to_market_notices"}),
            field_values={
                EngineModule.engine_mode: "auto",
                TradingRuleModule.accounting_mode: "Auto",
            },
        )
    })
    trading_days = pd.DatetimeIndex(["2026-03-10"] * 3)
    event_times = pd.DatetimeIndex([
        pd.Timestamp("2026-03-09 21:00:00", tz="Asia/Shanghai"),
        pd.Timestamp("2026-03-10 09:01:00", tz="Asia/Shanghai"),
        pd.Timestamp("2026-03-10 15:00:00", tz="Asia/Shanghai"),
    ])
    account.market_data_store.dmtm_event_table = pd.DataFrame(
        {"_DMTM_EVENT": [1.0, 1.0, 1.0]},
        index=pd.MultiIndex.from_arrays(
            [trading_days, event_times], names=["DAY1", "MIN1"]
        ),
    )
    # The flattened close table has a later calendar timestamp at 23:00;
    # DMTM must ignore that lossy grouping and use the source DAY1 axis.
    account.market_data_store.market_price_tables = {
        "close": pd.DataFrame(
            {"P1": [10.0, 11.0, 12.0]},
            index=pd.DatetimeIndex([
                pd.Timestamp("2026-03-09 21:00:00", tz="Asia/Shanghai"),
                pd.Timestamp("2026-03-10 09:01:00", tz="Asia/Shanghai"),
                pd.Timestamp("2026-03-10 23:00:00", tz="Asia/Shanghai"),
            ]),
        )
    }
    queue = EventQueue()
    captured = []
    queue.set_dispatcher(EventKind.LEDGER, lambda batch: captured.extend(batch))
    ctx = FlowContext(timestamp=None, event_queue=queue, active_strategies=frozenset({strategy}))

    _register_daily_mark_to_market_notices(account, ctx)
    queue.run_until_drained()

    assert len(captured) == 1
    assert captured[0].timestamp == pd.Timestamp("2026-03-10 15:00:00.000000001", tz="Asia/Shanghai")


def test_daily_mark_to_market_updates_cash_margin_and_settlement_basis():
    product = _product()
    strategy = Strategy(alias="S")
    config = StrategyConfig(
        strategy=strategy,
        active_flow_names=frozenset({"apply_daily_mark_to_market"}),
        field_values={
            EngineModule.engine_mode: "auto",
            TradingRuleModule.accounting_mode: "Auto",
            MarginModule.margin_mode: "auto",
        },
    )
    ledger = LedgerState(strategy=strategy, base_currency="CNY", ledger_id=f"private:{strategy.alias}")
    ledger.set(
        _positions_ref(),
        {
            product: ProductPosition(
                quantity=2.0,
                lots=deque([
                    Lot(quantity=2.0, entry_price=10.0, multiplier=10.0, is_today=False),
                ]),
                margin_reserved=DataMoney.from_major(2.0, currency="CNY", use_minor_units=False),
            )
        },
    )
    account = BacktestRunState(strategy_configs={strategy: config}, ledgers={f"private:{strategy.alias}": ledger})
    _set_cash(account, ledger, 1000.0)
    account.ledger_configs[ledger.ledger] = _ledger_config(accounting_mode="Auto", margin_mode="auto")
    queue = EventQueue()
    ctx = FlowContext(
        timestamp=pd.Timestamp("2026-03-10 15:00:00.000000001", tz="Asia/Shanghai"),
        event_queue=queue,
        active_strategies=frozenset({strategy}),
    )
    ctx.set(MarketDataModule.current_market_snapshot, {
        "settlement": {product: 12.0},
        "close": {product: 11.5},
    })
    ctx.set(MarketDataModule.current_prices, {})
    ctx.set(MarketDataModule.current_historical_fields, {
        product: {
            "VolumeMultiple": 10.0,
            "PreSettlementPrice": 10.0,
            "SettlementPrice": 12.0,
            "LongMarginRatioByMoney": 0.1,
        }
    })

    _apply_daily_mark_to_market(account, ctx)

    updated_cash = cash_for_ledger(account, ledger)
    updated_position = ledger.get(_positions_ref())[product]
    # DMTM settles variation PnL only: 2 * (12 - 10) * 10 = 40.
    # Margin requirement changes are handled by MarginModule notice flows.
    assert updated_cash.to_major() == pytest.approx(1040.0)
    assert updated_position.margin_reserved.to_major() == pytest.approx(2.0)
    assert updated_position.settlement_price == pytest.approx(12.0)
    assert updated_position.average_cost is None
    assert [(lot.quantity, lot.entry_price, lot.is_today) for lot in updated_position.lots] == [(2.0, 12.0, False)]


def test_exact_daily_mark_to_market_missing_settlement_falls_back_and_warns():
    product = _product()
    strategy = Strategy(alias="S")
    config = StrategyConfig(
        strategy=strategy,
        active_flow_names=frozenset({"apply_daily_mark_to_market"}),
        field_values={
            EngineModule.engine_mode: "auto",
            TradingRuleModule.accounting_mode: "Auto",
        },
    )
    ledger = LedgerState(strategy=strategy, base_currency="CNY", ledger_id=f"private:{strategy.alias}")
    ledger.set(_positions_ref(), {
        product: ProductPosition(
            quantity=2.0,
            lots=deque([Lot(quantity=2.0, entry_price=10.0, multiplier=10.0, is_today=False)]),
            settlement_price=10.0,
        )
    })
    account = BacktestRunState(strategy_configs={strategy: config}, ledgers={ledger.ledger: ledger})
    _set_cash(account, ledger, 1000.0)
    account.ledger_configs[ledger.ledger] = _ledger_config(accounting_mode="Auto", margin_mode="exact")
    ctx = FlowContext(
        timestamp=pd.Timestamp("2026-03-10 15:00:00.000000001", tz="Asia/Shanghai"),
        event_queue=EventQueue(),
        active_ledgers=frozenset({ledger.ledger}),
    )
    ctx.set(MarketDataModule.current_market_snapshot, {"close": {product: 12.0}})
    ctx.set(MarketDataModule.current_historical_fields, {
        product: {
            "VolumeMultiple": 10.0,
            "PreSettlementPrice": 10.0,
            "DailyMarkToMarketEnabled": True,
        }
    })

    _apply_daily_mark_to_market(account, ctx)

    entry = ledger.get(_positions_ref())[product]
    assert entry.settlement_price == pytest.approx(12.0)
    rows = [
        row for row in account.runtime_info_rows
        if row.get("code") == "daily_mark_to_market_price_fallback"
    ]
    assert len(rows) == 1
    assert rows[0]["details"]["fallback"] == "close"


def test_non_dmtm_ledger_event_does_not_apply_daily_mark_to_market_or_require_settlement():
    product = _product()
    strategy = Strategy(alias="S")
    config = StrategyConfig(
        strategy=strategy,
        active_flow_names=frozenset({"apply_daily_mark_to_market"}),
        field_values={
            EngineModule.engine_mode: "auto",
            TradingRuleModule.accounting_mode: "Auto",
        },
    )
    ledger = LedgerState(strategy=strategy, base_currency="CNY", ledger_id=f"private:{strategy.alias}")
    ledger.set(_positions_ref(), {
        product: ProductPosition(
            quantity=2.0,
            lots=deque([Lot(quantity=2.0, entry_price=10.0, multiplier=10.0, is_today=False)]),
            settlement_price=10.0,
        )
    })
    account = BacktestRunState(strategy_configs={strategy: config}, ledgers={ledger.ledger: ledger})
    _set_cash(account, ledger, 1000.0)
    account.ledger_configs[ledger.ledger] = _ledger_config(accounting_mode="Auto", margin_mode="exact")
    ctx = FlowContext(
        timestamp=pd.Timestamp("2026-03-10 09:01:00.000000002", tz="Asia/Shanghai"),
        event_queue=EventQueue(),
        active_ledgers=frozenset({ledger.ledger}),
        drafts_by_ledger={
            ledger.ledger: [EventDraft(
                EventKind.LEDGER,
                pd.Timestamp("2026-03-10 09:01:00.000000002", tz="Asia/Shanghai"),
                payload={"kind": "margin_check", "ledger_id": ledger.ledger.name},
                ledger=ledger.ledger,
            )],
        },
        event_kind=EventKind.LEDGER,
    )
    ctx.set(MarketDataModule.current_market_snapshot, {"close": {product: 12.0}})
    ctx.set(MarketDataModule.current_historical_fields, {
        product: {
            "VolumeMultiple": 10.0,
            "PreSettlementPrice": 10.0,
            "DailyMarkToMarketEnabled": True,
        }
    })

    _apply_daily_mark_to_market(account, ctx)

    assert _cash_major(account, ledger) == pytest.approx(1000.0)
    assert ledger.get(_positions_ref())[product].settlement_price == pytest.approx(10.0)


def test_exact_daily_mark_to_market_settlement_notice_updates_ledger():
    product = _product()
    strategy = Strategy(alias="S")
    config = StrategyConfig(
        strategy=strategy,
        active_flow_names=frozenset({"apply_daily_mark_to_market"}),
        field_values={
            EngineModule.engine_mode: "auto",
            TradingRuleModule.accounting_mode: "Auto",
        },
    )
    ledger = LedgerState(strategy=strategy, base_currency="CNY", ledger_id=f"private:{strategy.alias}")
    ledger.set(_positions_ref(), {
        product: ProductPosition(
            quantity=2.0,
            lots=deque([Lot(quantity=2.0, entry_price=10.0, multiplier=10.0, is_today=False)]),
            settlement_price=10.0,
        )
    })
    account = BacktestRunState(strategy_configs={strategy: config}, ledgers={ledger.ledger: ledger})
    _set_cash(account, ledger, 1000.0)
    account.ledger_configs[ledger.ledger] = _ledger_config(accounting_mode="Auto", margin_mode="exact")
    ctx = FlowContext(
        timestamp=pd.Timestamp("2026-03-10 15:00:00.000000001", tz="Asia/Shanghai"),
        event_queue=EventQueue(),
        active_ledgers=frozenset({ledger.ledger}),
    )
    ctx.set(MarketDataModule.current_market_snapshot, {
        "settlement": {product: 12.0},
        "close": {product: 11.5},
    })
    ctx.set(MarketDataModule.current_historical_fields, {
        product: {
            "VolumeMultiple": 10.0,
            "PreSettlementPrice": 10.0,
            "SettlementPrice": 12.0,
            "DailyMarkToMarketEnabled": True,
        }
    })

    _apply_daily_mark_to_market(account, ctx)

    assert _cash_major(account, ledger) == pytest.approx(1040.0)
    updated_position = ledger.get(_positions_ref())[product]
    assert updated_position.settlement_price == pytest.approx(12.0)
    assert [(lot.quantity, lot.entry_price, lot.is_today) for lot in updated_position.lots] == [(2.0, 12.0, False)]


def test_daily_mark_to_market_then_margin_then_next_morning_equity_matches_formula():
    from tools.testers.backtest.modules.ledger_module import LedgerModule, _basic_equity

    product = _product()
    strategy = Strategy(alias="S")
    config = StrategyConfig(
        strategy=strategy,
        active_flow_names=frozenset({
            "apply_daily_mark_to_market",
            "apply_margin_requirement_change",
            "equity_on_signal",
        }),
        field_values={
            EngineModule.engine_mode: "auto",
            TradingRuleModule.accounting_mode: "Auto",
            MarginModule.margin_mode: "auto",
        },
    )
    ledger = LedgerState(strategy=strategy, base_currency="CNY", ledger_id=f"private:{strategy.alias}")
    ledger.set(
        _positions_ref(),
        {
            product: ProductPosition(
                quantity=2.0,
                lots=deque([
                    Lot(quantity=2.0, entry_price=10.0, multiplier=10.0, is_today=False),
                ]),
                settlement_price=10.0,
                margin_reserved=DataMoney.from_major(20.0, currency="CNY", use_minor_units=False),
            )
        },
    )
    state = BacktestRunState(strategy_configs={strategy: config}, ledgers={ledger.ledger: ledger})
    _set_cash(state, ledger, 1000.0)
    state.ledger_configs[ledger.ledger] = _ledger_config(accounting_mode="Auto", margin_mode="auto")

    settlement_fields = {
        "VolumeMultiple": 10.0,
        "PreSettlementPrice": 10.0,
        "SettlementPrice": 12.0,
        "LongMarginRatioByMoney": 0.1,
    }
    dmtm_ctx = FlowContext(
        timestamp=pd.Timestamp("2026-03-10 15:00:00.000000001", tz="Asia/Shanghai"),
        event_queue=EventQueue(),
        active_ledgers=frozenset({ledger.ledger}),
    )
    dmtm_ctx.set(MarketDataModule.current_market_snapshot, {
        "settlement": {product: 12.0},
        "close": {product: 11.5},
    })
    dmtm_ctx.set(MarketDataModule.current_historical_fields, {product: settlement_fields})

    _apply_daily_mark_to_market(state, dmtm_ctx)

    position = ledger.get(_positions_ref())[product]
    assert cash_for_ledger(state, ledger).to_major() == pytest.approx(1040.0)
    assert position.settlement_price == pytest.approx(12.0)
    assert position.margin_reserved.to_major() == pytest.approx(20.0)
    assert [(lot.quantity, lot.entry_price, lot.is_today) for lot in position.lots] == [(2.0, 12.0, False)]

    margin_ctx = FlowContext(
        timestamp=pd.Timestamp("2026-03-10 15:00:00.000000002", tz="Asia/Shanghai"),
        event_queue=EventQueue(),
        active_ledgers=frozenset({ledger.ledger}),
        drafts_by_ledger={
            ledger.ledger: [
                EventDraft(
                    EventKind.LEDGER,
                    pd.Timestamp("2026-03-10 15:00:00.000000002", tz="Asia/Shanghai"),
                    payload={"kind": "margin_check", "ledger_id": ledger.ledger_id},
                    ledger=ledger.ledger,
                )
            ]
        },
    )
    margin_ctx.set(MarketDataModule.current_market_snapshot, {
        "settlement": {product: 12.0},
        "close": {product: 11.5},
    })
    margin_ctx.set(MarketDataModule.current_historical_fields, {product: settlement_fields})

    _apply_margin_requirement_change(state, margin_ctx)

    position = ledger.get(_positions_ref())[product]
    assert position.margin_reserved.to_major() == pytest.approx(24.0)
    assert ledger.get(MarginModule.margin_requirement) == pytest.approx(24.0)
    assert ledger.get(MarginModule.margin_reserved) == pytest.approx(24.0)
    assert ledger.get(MarginModule.margin_deficit) == pytest.approx(0.0)
    assert cash_for_ledger(state, ledger).to_major() == pytest.approx(1036.0)

    next_morning_ctx = FlowContext(
        timestamp=pd.Timestamp("2026-03-11 09:30:00", tz="Asia/Shanghai"),
        event_queue=EventQueue(),
        active_strategies=frozenset({strategy}),
    )
    next_morning_ctx.set(MarketDataModule.current_prices, {product: 13.0})
    next_morning_ctx.set(MarketDataModule.current_historical_fields, {
        product: {"VolumeMultiple": 10.0, "SettlementPrice": 12.0}
    })

    _basic_equity(state, next_morning_ctx)

    # 15:00 DMTM realizes 2 * (12 - 10) * 10 = 40 into cash.
    # The margin notice moves another 4 from cash to reserved margin.
    # Next morning equity is cash + reserved margin + floating PnL from
    # last settlement: 1036 + 24 + 2 * (13 - 12) * 10 = 1080.
    assert next_morning_ctx.get_for(LedgerModule.equity, strategy) == pytest.approx(1080.0)


def test_daily_mark_to_market_ignores_zero_settlement_placeholder_and_uses_close_in_auto_mode():
    product = _product()
    strategy = Strategy(alias="S")
    config = StrategyConfig(
        strategy=strategy,
        active_flow_names=frozenset({"apply_daily_mark_to_market"}),
        field_values={
            EngineModule.engine_mode: "auto",
            TradingRuleModule.accounting_mode: "Auto",
        },
    )
    ledger = LedgerState(strategy=strategy, base_currency="CNY", ledger_id=f"private:{strategy.alias}")
    ledger.set(_positions_ref(), {
        product: ProductPosition(
            quantity=2.0,
            lots=deque([Lot(quantity=2.0, entry_price=10.0, multiplier=10.0, is_today=False)]),
            settlement_price=10.0,
        )
    })
    state = BacktestRunState(strategy_configs={strategy: config}, ledgers={ledger.ledger: ledger})
    _set_cash(state, ledger, 1000.0)
    state.ledger_configs[ledger.ledger] = _ledger_config(accounting_mode="Auto")
    ctx = FlowContext(
        timestamp=pd.Timestamp("2026-03-10 15:00:00.000000001", tz="Asia/Shanghai"),
        event_queue=EventQueue(),
        active_ledgers=frozenset({ledger.ledger}),
    )
    ctx.set(MarketDataModule.current_market_snapshot, {
        "settlement": {product: 0.0},
        "close": {product: 12.0},
    })
    ctx.set(MarketDataModule.current_historical_fields, {
        product: {
            "VolumeMultiple": 10.0,
            "PreSettlementPrice": 10.0,
            "SettlementPrice": 0.0,
            "CloseTodayRatioByMoney": 0.0,
        }
    })

    _apply_daily_mark_to_market(state, ctx)

    position = ledger.get(_positions_ref())[product]
    assert cash_for_ledger(state, ledger).to_major() == pytest.approx(1040.0)
    assert position.settlement_price == pytest.approx(12.0)
    assert [(lot.quantity, lot.entry_price) for lot in position.lots] == [(2.0, 12.0)]


def test_daily_mark_to_market_records_settlement_close_fallback_interval():
    product = _product()
    strategy = Strategy(alias="S")
    config = StrategyConfig(
        strategy=strategy,
        active_flow_names=frozenset({"apply_daily_mark_to_market"}),
        field_values={
            EngineModule.engine_mode: "auto",
            TradingRuleModule.accounting_mode: "Auto",
        },
    )
    ledger = LedgerState(strategy=strategy, base_currency="CNY", ledger_id=f"private:{strategy.alias}")
    ledger.set(_positions_ref(), {
        product: ProductPosition(
            quantity=2.0,
            lots=deque([Lot(quantity=2.0, entry_price=10.0, multiplier=10.0, is_today=False)]),
            settlement_price=10.0,
        )
    })
    state = BacktestRunState(strategy_configs={strategy: config}, ledgers={ledger.ledger: ledger})
    _set_cash(state, ledger, 1000.0)
    state.ledger_configs[ledger.ledger] = _ledger_config(accounting_mode="Auto")

    for timestamp, close in (
        (pd.Timestamp("2026-03-10 15:00:00.000000001", tz="Asia/Shanghai"), 12.0),
        (pd.Timestamp("2026-03-11 15:00:00.000000001", tz="Asia/Shanghai"), 13.0),
    ):
        ctx = FlowContext(
            timestamp=timestamp,
            event_queue=EventQueue(),
            active_ledgers=frozenset({ledger.ledger}),
        )
        ctx.set(MarketDataModule.current_market_snapshot, {
            "settlement": {product: 0.0},
            "close": {product: close},
        })
        ctx.set(MarketDataModule.current_historical_fields, {
            product: {
                "VolumeMultiple": 10.0,
                "PreSettlementPrice": 10.0,
                "SettlementPrice": 0.0,
            }
        })

        _apply_daily_mark_to_market(state, ctx)

    rows = [row for row in state.runtime_info_rows if row.get("code") == "daily_mark_to_market_price_fallback"]
    assert len(rows) == 1
    details = rows[0]["details"]
    assert details["source"] == "settlement"
    assert details["fallback"] == "close"
    assert details["count"] == 2
    assert details["start"].startswith("2026-03-10")
    assert details["end"].startswith("2026-03-11")


def test_exact_daily_mark_to_market_missing_all_prices_reports_event_context():
    product = _product()

    with pytest.raises(KeyError) as exc:
        _settlement_price_for_product(
            product,
            {},
            {},
            {},
            require_exact=True,
            timestamp=pd.Timestamp("2024-02-23 00:00:00.000000001", tz="Asia/Shanghai"),
            trading_day="2024-02-22",
        )

    message = str(exc.value)
    assert f"settlement price for {product}" in message
    assert "timestamp=2024-02-23 00:00:00.000000001+08:00" in message
    assert "trading_day=2024-02-22" in message
    assert "source=market_snapshot.settlement" in message


def test_daily_mark_to_market_fallback_interval_dedupes_multiple_ledgers_same_timestamp():
    product = _product()
    strategies = [Strategy(alias="S1"), Strategy(alias="S2")]
    configs = {
        strategy: StrategyConfig(
            strategy=strategy,
            active_flow_names=frozenset({"apply_daily_mark_to_market"}),
            field_values={
                EngineModule.engine_mode: "auto",
                TradingRuleModule.accounting_mode: "Auto",
            },
        )
        for strategy in strategies
    }
    ledgers = {}
    for strategy in strategies:
        ledger = LedgerState(strategy=strategy, base_currency="CNY", ledger_id=f"private:{strategy.alias}")
        ledger.set(_positions_ref(), {
            product: ProductPosition(
                quantity=2.0,
                lots=deque([Lot(quantity=2.0, entry_price=10.0, multiplier=10.0, is_today=False)]),
                settlement_price=10.0,
            )
        })
        ledgers[ledger.ledger] = ledger
    state = BacktestRunState(strategy_configs=configs, ledgers=ledgers)
    for ledger in ledgers.values():
        _set_cash(state, ledger, 1000.0)
        state.ledger_configs[ledger.ledger] = _ledger_config(accounting_mode="Auto")

    timestamp = pd.Timestamp("2026-03-10 15:00:00.000000001", tz="Asia/Shanghai")
    ctx = FlowContext(
        timestamp=timestamp,
        event_queue=EventQueue(),
        active_ledgers=frozenset(ledgers),
    )
    ctx.set(MarketDataModule.current_market_snapshot, {
        "settlement": {product: 0.0},
        "close": {product: 12.0},
    })
    ctx.set(MarketDataModule.current_historical_fields, {
        product: {
            "VolumeMultiple": 10.0,
            "PreSettlementPrice": 10.0,
            "SettlementPrice": 0.0,
        }
    })

    _apply_daily_mark_to_market(state, ctx)

    rows = [row for row in state.runtime_info_rows if row.get("code") == "daily_mark_to_market_price_fallback"]
    assert len(rows) == 1
    assert rows[0]["details"]["count"] == 1


def test_daily_mark_to_market_missing_previous_basis_does_not_fallback_to_current_settlement():
    product = _product()
    strategy = Strategy(alias="S")
    config = StrategyConfig(
        strategy=strategy,
        active_flow_names=frozenset({"apply_daily_mark_to_market"}),
        field_values={
            EngineModule.engine_mode: "auto",
            TradingRuleModule.accounting_mode: "Auto",
        },
    )
    ledger = LedgerState(strategy=strategy, base_currency="CNY", ledger_id=f"private:{strategy.alias}")
    ledger.set(_positions_ref(), {product: ProductPosition(quantity=2.0)})
    state = BacktestRunState(strategy_configs={strategy: config}, ledgers={ledger.ledger: ledger})
    _set_cash(state, ledger, 1000.0)
    state.ledger_configs[ledger.ledger] = _ledger_config(accounting_mode="Auto")
    ctx = FlowContext(
        timestamp=pd.Timestamp("2026-03-10 15:00:00.000000001", tz="Asia/Shanghai"),
        event_queue=EventQueue(),
        active_ledgers=frozenset({ledger.ledger}),
    )
    ctx.set(MarketDataModule.current_market_snapshot, {
        "settlement": {product: 12.0},
        "close": {product: 12.0},
    })
    ctx.set(MarketDataModule.current_historical_fields, {
        product: {"VolumeMultiple": 10.0, "SettlementPrice": 12.0}
    })

    with pytest.raises(KeyError, match="previous settlement price or position basis"):
        _apply_daily_mark_to_market(state, ctx)


def test_daily_mark_to_market_short_position_updates_cash_margin_and_settlement_basis():
    product = _product()
    strategy = Strategy(alias="S")
    config = StrategyConfig(
        strategy=strategy,
        active_flow_names=frozenset({"apply_daily_mark_to_market"}),
        field_values={
            EngineModule.engine_mode: "auto",
            TradingRuleModule.accounting_mode: "Auto",
            MarginModule.margin_mode: "auto",
        },
    )
    ledger = LedgerState(strategy=strategy, base_currency="CNY")
    ledger.set(_positions_ref(), {
        product: ProductPosition(
            quantity=-2.0,
            lots=deque([
                Lot(quantity=-2.0, entry_price=10.0, multiplier=10.0, is_today=False),
            ]),
            margin_reserved=DataMoney.from_major(2.0, currency="CNY", use_minor_units=False),
        )
    })
    account = BacktestRunState(strategy_configs={strategy: config}, ledgers={f"private:{strategy.alias}": ledger})
    _set_cash(account, ledger, 1000.0)
    account.ledger_configs[ledger.ledger] = _ledger_config(accounting_mode="Auto", margin_mode="auto")
    ctx = FlowContext(
        timestamp=pd.Timestamp("2026-03-10 15:00:00.000000001", tz="Asia/Shanghai"),
        event_queue=EventQueue(),
        active_strategies=frozenset({strategy}),
    )
    ctx.set(MarketDataModule.current_market_snapshot, {"settlement": {product: 12.0}, "close": {product: 12.0}})
    ctx.set(MarketDataModule.current_historical_fields, {
        product: {
            "VolumeMultiple": 10.0,
            "SettlementPrice": 12.0,
            "ShortMarginRatioByMoney": 0.1,
        }
    })

    _apply_daily_mark_to_market(account, ctx)

    updated_cash = cash_for_ledger(account, ledger)
    updated_position = ledger.get(_positions_ref())[product]
    # Short PnL = -2 * (12 - 10) * 10 = -40. Margin requirement changes
    # are handled by MarginModule notice flows, not DMTM.
    assert updated_cash.to_major() == pytest.approx(960.0)
    assert updated_position.margin_reserved.to_major() == pytest.approx(2.0)
    assert updated_position.settlement_price == pytest.approx(12.0)
    assert [(lot.quantity, lot.entry_price, lot.is_today) for lot in updated_position.lots] == [(-2.0, 12.0, False)]


def test_daily_mark_to_market_shared_ledger_settles_once_per_ledger():
    product = _product()
    s1 = Strategy(alias="S1")
    s2 = Strategy(alias="S2")
    config1 = StrategyConfig(
        strategy=s1,
        active_flow_names=frozenset({"apply_daily_mark_to_market"}),
        field_values={EngineModule.engine_mode: "auto", TradingRuleModule.accounting_mode: "Auto"},
    )
    config2 = StrategyConfig(
        strategy=s2,
        active_flow_names=frozenset({"apply_daily_mark_to_market"}),
        field_values={EngineModule.engine_mode: "auto", TradingRuleModule.accounting_mode: "Auto"},
    )
    ledger_key = ledger_identity("shared-book")
    ledger = LedgerState(strategy=s1, base_currency="CNY", ledger=ledger_key)
    ledger.set(_positions_ref(), {
        product: ProductPosition(
            quantity=1.0,
            lots=deque([Lot(quantity=1.0, entry_price=10.0, multiplier=1.0, is_today=False)]),
            settlement_price=10.0,
            margin_reserved=DataMoney.from_major(1.0, currency="CNY", use_minor_units=False),
        )
    })
    account = BacktestRunState(strategy_configs={s1: config1, s2: config2}, ledgers={ledger_key: ledger})
    _set_cash(account, ledger, 100.0)
    account.ledger_configs[ledger_key] = _ledger_config(accounting_mode="Auto", margin_mode="auto")
    ctx = FlowContext(
        timestamp=pd.Timestamp("2026-03-10 15:00:00.000000001", tz="Asia/Shanghai"),
        event_queue=EventQueue(),
        active_ledgers=frozenset({ledger_key}),
        drafts_by_ledger={
            ledger_key: [
                EventDraft(
                    EventKind.LEDGER,
                    pd.Timestamp("2026-03-10 15:00:00.000000001", tz="Asia/Shanghai"),
                    payload={"kind": "daily_mark_to_market", "ledger_id": "shared-book"},
                    ledger=ledger_key,
                )
            ]
        },
    )
    ctx.set(MarketDataModule.current_market_snapshot, {"settlement": {product: 12.0}, "close": {product: 12.0}})
    ctx.set(MarketDataModule.current_historical_fields, {
        product: {
            "VolumeMultiple": 1.0,
            "SettlementPrice": 12.0,
            "LongMarginRatioByMoney": 0.1,
        }
    })

    _apply_daily_mark_to_market(account, ctx)

    # One settlement: pnl +2.0. If this were still strategy-scoped, the shared
    # ledger would be settled twice.
    assert _cash_major(account, ledger) == pytest.approx(102.0)
    entry = ledger.get(_positions_ref())[product]
    assert entry.margin_reserved.to_major() == pytest.approx(1.0)
    assert [(lot.quantity, lot.entry_price, lot.is_today) for lot in entry.lots] == [(1.0, 12.0, False)]


def test_ledger_dispatch_loads_market_data_and_settles_ledger_once():
    product = _product()
    s1 = Strategy(alias="S1")
    s2 = Strategy(alias="S2")
    flow_names = frozenset({
        "lookup_current_prices_on_ledger",
        "lookup_historical_fields_on_ledger",
        "apply_daily_mark_to_market",
    })
    account = BacktestRunState(strategy_configs={
        s1: StrategyConfig(
            strategy=s1,
            active_flow_names=flow_names,
            field_values={EngineModule.engine_mode: "auto", TradingRuleModule.accounting_mode: "Auto"},
        ),
        s2: StrategyConfig(
            strategy=s2,
            active_flow_names=flow_names,
            field_values={EngineModule.engine_mode: "auto", TradingRuleModule.accounting_mode: "Auto"},
        ),
    })
    ledger = ledger_identity("shared-book")
    shared = LedgerState(strategy=s1, base_currency="CNY", ledger=ledger)
    shared.set(_positions_ref(), {
        product: ProductPosition(
            quantity=1.0,
            lots=deque([Lot(quantity=1.0, entry_price=10.0, multiplier=1.0, is_today=False)]),
            settlement_price=10.0,
            margin_reserved=DataMoney.from_major(1.0, currency="CNY", use_minor_units=False),
        )
    })
    account.ledgers = {ledger: shared}
    _set_cash(account, shared, 100.0)
    account.ledger_configs[ledger] = _ledger_config(accounting_mode="Auto", margin_mode="auto")
    store = strategy_book_store_for(account)
    store.register_strategy_ledgers(s1, (ledger.name,), default_ledger_id=ledger.name)
    store.register_strategy_ledgers(s2, (ledger.name,), default_ledger_id=ledger.name)

    event_time = pd.Timestamp("2026-03-10 15:00:00.000000001", tz="Asia/Shanghai")
    market_time = event_time - pd.Timedelta(nanoseconds=1)
    close = pd.DataFrame({product: [12.0]}, index=pd.DatetimeIndex([market_time]))
    settlement = pd.DataFrame({product: [12.0]}, index=pd.DatetimeIndex([market_time]))
    account.market_data_store.current_prices_table = close
    account.market_data_store.market_price_tables = {"settlement": settlement}
    account.market_data_store.historical_field_provider = object()
    account.market_data_store.trading_day_resolver = object()
    account.market_data_store.historical_field_names = (
        "VolumeMultiple",
        "SettlementPrice",
        "LongMarginRatioByMoney",
    )
    field_index = pd.DatetimeIndex([market_time.tz_localize(None)])
    account.market_data_store.historical_field_frames = {
        "VolumeMultiple": pd.DataFrame({product: [1.0]}, index=field_index),
        "SettlementPrice": pd.DataFrame({product: [12.0]}, index=field_index),
        "LongMarginRatioByMoney": pd.DataFrame({product: [0.1]}, index=field_index),
    }

    registry = FlowRegistry()
    for flow in (
        MarketDataModule.lookup_current_prices_on_ledger,
        MarketDataModule.lookup_historical_fields_on_ledger,
        TradingRuleModule.apply_daily_mark_to_market,
    ):
        registry.register_flow(flow)
    groups = sort_and_validate(registry.resolve())
    queue = EventQueue()
    dispatcher = make_dispatcher(groups[(TradingRuleModule.apply_daily_mark_to_market.phase, EventKind.LEDGER)], account, queue)
    queue.set_dispatcher(EventKind.LEDGER, dispatcher)
    queue.push_event(EventDraft(
        EventKind.LEDGER,
        event_time,
        payload={"kind": "daily_mark_to_market", "ledger_id": ledger.name},
        ledger=ledger,
    ))

    queue.run_until_drained()

    # MarketData lookup flows must have fed the ledger-scoped DMTM flow. The
    # shared ledger is attached to two strategies, but the notice itself is a
    # ledger event, so settlement happens once: +2 PnL.
    assert _cash_major(account, shared) == pytest.approx(102.0)
    entry = shared.get(_positions_ref())[product]
    assert entry.margin_reserved.to_major() == pytest.approx(1.0)
    assert [(lot.quantity, lot.entry_price, lot.is_today) for lot in entry.lots] == [(1.0, 12.0, False)]


def test_margin_check_dispatch_enters_trade_intent_before_order():
    product = _product()
    strategy = Strategy(alias="S")
    flow_names = frozenset({
        "lookup_current_prices_on_ledger",
        "lookup_historical_fields_on_ledger",
        "lookup_current_prices_on_trade_intent",
        "lookup_historical_fields_on_trade_intent",
        "apply_margin_requirement_change",
        "handle_margin_liquidation_notice",
    })
    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            active_flow_names=flow_names,
            field_values={EngineModule.engine_mode: "auto"},
        ),
    })
    ledger_key = ledger_identity("risk-book")
    ledger = LedgerState(strategy=strategy, base_currency="CNY", ledger=ledger_key)
    ledger.set(_positions_ref(), {
        product: ProductPosition(
            quantity=2.0,
            lots=deque([Lot(quantity=2.0, entry_price=10.0, multiplier=10.0, is_today=False)]),
            margin_reserved=DataMoney.from_major(2.0, currency="CNY", use_minor_units=False),
        )
    })
    account.ledgers = {ledger_key: ledger}
    _set_cash(account, ledger, 10.0)
    account.ledger_configs[ledger_key] = _ledger_config(
        margin_mode="auto",
        margin_call_mode="liquidate",
        liquidation_target_buffer=0.0,
    )
    strategy_book_store_for(account).register_strategy_ledgers(
        strategy,
        (ledger_key.name,),
        default_ledger_id=ledger_key.name,
    )

    event_time = pd.Timestamp("2026-03-10 15:00:00.000000002", tz="Asia/Shanghai")
    market_time = event_time - pd.Timedelta(nanoseconds=2)
    next_market_time = market_time + pd.Timedelta(minutes=1)
    close = pd.DataFrame(
        {product: [12.0, 12.5]},
        index=pd.DatetimeIndex([market_time, next_market_time]),
    )
    account.market_data_store.current_prices_table = close
    account.market_data_store.market_price_tables = {
        "open": pd.DataFrame(
            {product: [11.5, 12.25]},
            index=pd.DatetimeIndex([market_time, next_market_time]),
        ),
        "close": close,
    }
    account.market_data_store.historical_field_names = (
        "VolumeMultiple",
        "LongMarginRatioByMoney",
    )
    account.market_data_store.historical_field_provider = object()
    account.market_data_store.trading_day_resolver = object()
    field_index = pd.DatetimeIndex([market_time.tz_localize(None)])
    account.market_data_store.historical_field_frames = {
        "VolumeMultiple": pd.DataFrame({product: [10.0]}, index=field_index),
        "LongMarginRatioByMoney": pd.DataFrame({product: [0.1]}, index=field_index),
    }

    registry = FlowRegistry()
    for flow in (
        MarketDataModule.lookup_current_prices_on_ledger,
        MarketDataModule.lookup_historical_fields_on_ledger,
        MarketDataModule.lookup_current_prices_on_trade_intent,
        MarketDataModule.lookup_historical_fields_on_trade_intent,
        MarginModule.apply_margin_requirement_change,
        MarginModule.handle_margin_liquidation_notice,
    ):
        registry.register_flow(flow)
    groups = sort_and_validate(registry.resolve())
    queue = EventQueue()
    captured_orders: list[EventDraft] = []
    queue.set_dispatcher(
        EventKind.LEDGER,
        make_dispatcher(groups[(MarginModule.apply_margin_requirement_change.phase, EventKind.LEDGER)], account, queue),
    )
    queue.set_dispatcher(
        EventKind.TRADE_INTENT,
        make_dispatcher(groups[(MarginModule.handle_margin_liquidation_notice.phase, EventKind.TRADE_INTENT)], account, queue),
    )
    queue.set_dispatcher(EventKind.ORDER, lambda batch: captured_orders.extend(batch))
    queue.push_event(EventDraft(
        EventKind.LEDGER,
        event_time,
        payload={"kind": "margin_check", "ledger_id": ledger_key.name},
        ledger=ledger_key,
    ))

    queue.run_until_drained()

    assert ledger.get(MarginModule.margin_requirement) == pytest.approx(20.0)
    assert ledger.get(MarginModule.margin_deficit) == pytest.approx(15.2)
    assert ledger.get(MarginModule.margin_utilization) == pytest.approx(20.0 / 12.0)
    assert ledger.get(MarginModule.margin_limit_excess) == pytest.approx(15.2)
    assert captured_orders
    attempt = captured_orders[0].payload
    order = attempt.order
    assert captured_orders[0].timestamp == market_time + pd.Timedelta(microseconds=1)
    assert attempt.market_timestamp == next_market_time
    assert attempt.attempt_id
    assert account.order_store.attempts_by_id[attempt.attempt_id] is attempt
    assert account.order_store.orders_by_id[order.order_id] is order
    assert order.get("active_attempt_id", "") == ""
    assert order.instrument is product
    assert order.quantity < 0
    assert order.get("execution_price_basis") == "open"
    assert order.get("liquidation_reason") == "margin_deficit"


def test_daily_mark_to_market_uses_blended_intraday_basis_after_same_day_add():
    product = _product()
    strategy = Strategy(alias="S")
    config = StrategyConfig(
        strategy=strategy,
        active_flow_names=frozenset({"apply_daily_mark_to_market"}),
        field_values={
            EngineModule.engine_mode: "auto",
            TradingRuleModule.accounting_mode: "Auto",
            MarginModule.margin_mode: "auto",
        },
    )
    ledger = LedgerState(strategy=strategy, base_currency="CNY")
    ledger.set(
        _positions_ref(),
        {
            product: ProductPosition(
                quantity=2.0,
                lots=deque([
                    Lot(quantity=1.0, entry_price=20.0, multiplier=1.0, is_today=False),
                    Lot(quantity=1.0, entry_price=10.0, multiplier=1.0, is_today=True),
                ]),
                settlement_price=20.0,  # stale previous settlement for the old lot only
                margin_reserved=DataMoney.from_major(4.0, currency="CNY", use_minor_units=False),
            )
        },
    )
    account = BacktestRunState(strategy_configs={strategy: config}, ledgers={f"private:{strategy.alias}": ledger})
    _set_cash(account, ledger, 1000.0)
    account.ledger_configs[ledger.ledger] = _ledger_config(accounting_mode="Auto", margin_mode="auto")
    ctx = FlowContext(
        timestamp=pd.Timestamp("2026-03-10 15:00:00.000000001", tz="Asia/Shanghai"),
        event_queue=EventQueue(),
        active_strategies=frozenset({strategy}),
    )
    ctx.set(MarketDataModule.current_market_snapshot, {
        "settlement": {product: 18.0},
        "close": {product: 18.0},
    })
    ctx.set(MarketDataModule.current_historical_fields, {
        product: {
            "VolumeMultiple": 1.0,
            "SettlementPrice": 18.0,
            "LongMarginRatioByMoney": 0.1,
        }
    })

    _apply_daily_mark_to_market(account, ctx)

    updated_cash = cash_for_ledger(account, ledger)
    updated_position = ledger.get(_positions_ref())[product]
    # Correct PnL: old lot (18-20) + new lot (18-10) = +6, equivalent to
    # 2 * (18 - blended_basis 15). The stale settlement tag alone would
    # produce 2 * (18 - 20) = -4 and an artificial equity drop.
    # Margin requirement changes are handled by MarginModule notice flows.
    assert updated_cash.to_major() == pytest.approx(1006.0)
    assert updated_position.margin_reserved.to_major() == pytest.approx(4.0)
    assert updated_position.settlement_price == pytest.approx(18.0)
    assert updated_position.average_cost is None
    assert [(lot.quantity, lot.entry_price, lot.is_today) for lot in updated_position.lots] == [(2.0, 18.0, False)]


def test_daily_mark_to_market_prefers_lot_basis_even_when_equal_to_current_settlement():
    product = _product()
    strategy = Strategy(alias="S")
    config = StrategyConfig(
        strategy=strategy,
        active_flow_names=frozenset({"apply_daily_mark_to_market"}),
        field_values={
            EngineModule.engine_mode: "auto",
            TradingRuleModule.accounting_mode: "Auto",
            MarginModule.margin_mode: "auto",
        },
    )
    ledger = LedgerState(strategy=strategy, base_currency="CNY")
    ledger.set(_positions_ref(), {
        product: ProductPosition(
            quantity=1.0,
            lots=deque([Lot(quantity=1.0, entry_price=18.0, multiplier=1.0, is_today=True)]),
            settlement_price=20.0,
            margin_reserved=DataMoney.from_major(2.0, currency="CNY", use_minor_units=False),
        )
    })
    account = BacktestRunState(strategy_configs={strategy: config}, ledgers={f"private:{strategy.alias}": ledger})
    _set_cash(account, ledger, 1000.0)
    account.ledger_configs[ledger.ledger] = _ledger_config(accounting_mode="Auto", margin_mode="auto")
    ctx = FlowContext(
        timestamp=pd.Timestamp("2026-03-10 15:00:00.000000001", tz="Asia/Shanghai"),
        event_queue=EventQueue(),
        active_strategies=frozenset({strategy}),
    )
    ctx.set(MarketDataModule.current_market_snapshot, {
        "settlement": {product: 18.0},
        "close": {product: 18.0},
    })
    ctx.set(MarketDataModule.current_historical_fields, {
        product: {
            "VolumeMultiple": 1.0,
            "PreSettlementPrice": 20.0,
            "SettlementPrice": 18.0,
            "LongMarginRatioByMoney": 0.1,
        }
    })

    _apply_daily_mark_to_market(account, ctx)

    # PnL is zero because the open lot's basis is already 18. The historical
    # PreSettlementPrice belongs to old inventory and must not override lots.
    assert _cash_major(account, ledger) == pytest.approx(1000.0)
    entry = ledger.get(_positions_ref())[product]
    assert [(lot.quantity, lot.entry_price, lot.is_today) for lot in entry.lots] == [(1.0, 18.0, False)]


def test_margin_requirement_change_never_makes_cash_negative_and_emits_liquidation_notice():
    product = _product()
    strategy = Strategy(alias="S")
    ledger = LedgerState(strategy=strategy, base_currency="CNY")
    ledger.set(_positions_ref(), {
        product: ProductPosition(
            quantity=2.0,
            lots=deque([Lot(quantity=2.0, entry_price=10.0, multiplier=10.0, is_today=False)]),
            margin_reserved=DataMoney.from_major(2.0, currency="CNY", use_minor_units=False),
        )
    })
    state = BacktestRunState(
        strategy_configs={strategy: StrategyConfig(strategy=strategy, field_values={EngineModule.engine_mode: "auto"})},
        ledgers={f"private:{strategy.alias}": ledger},
    )
    _set_cash(state, ledger, 10.0)
    state.ledger_configs[ledger.ledger] = LedgerConfig(margin_mode="auto", margin_call_mode="liquidate")
    event_time = pd.Timestamp("2026-03-10 15:00:00.000000002", tz="Asia/Shanghai")
    queue = EventQueue()
    ctx = FlowContext(
        timestamp=event_time,
        event_queue=queue,
        active_ledgers=frozenset({ledger.ledger}),
        drafts_by_ledger={
            ledger.ledger: [EventDraft(
                EventKind.LEDGER,
                event_time,
                payload={"kind": "margin_check", "ledger_id": ledger.ledger_id},
                ledger=ledger.ledger,
            )],
        },
    )
    ctx.set(MarketDataModule.current_market_snapshot, {"settlement": {product: 12.0}, "close": {product: 12.0}})
    ctx.set(MarketDataModule.current_historical_fields, {
        product: {
            "VolumeMultiple": 10.0,
            "LongMarginRatioByMoney": 0.1,
        }
    })

    _apply_margin_requirement_change(state, ctx)

    entry = ledger.get(_positions_ref())[product]
    assert _cash_major(state, ledger) == pytest.approx(0.0)
    assert entry.margin_reserved.to_major() == pytest.approx(12.0)
    assert ledger.get(MarginModule.margin_requirement) == pytest.approx(20.0)
    assert ledger.get(MarginModule.margin_deficit) == pytest.approx(15.2)
    assert ledger.get(MarginModule.margin_utilization) == pytest.approx(20.0 / 12.0)
    assert ledger.get(MarginModule.margin_limit_excess) == pytest.approx(15.2)
    assert queue.pending_count_by_kind(EventKind.TRADE_INTENT) == 1
    assert queue.pending_count_by_kind(EventKind.ORDER) == 0


def test_margin_requirement_uses_position_fill_basis_not_market_snapshot_price():
    product = _product()
    other_product = _product()
    strategy = Strategy(alias="S")
    ledger = LedgerState(strategy=strategy, base_currency="CNY")
    ledger.set(_positions_ref(), {
        product: ProductPosition(
            quantity=2.0,
            lots=deque([Lot(quantity=2.0, entry_price=10.0, multiplier=10.0, is_today=False)]),
            margin_reserved=DataMoney.from_major(2.0, currency="CNY", use_minor_units=False),
        )
    })
    state = BacktestRunState(
        strategy_configs={strategy: StrategyConfig(strategy=strategy, field_values={EngineModule.engine_mode: "auto"})},
        ledgers={f"private:{strategy.alias}": ledger},
    )
    _set_cash(state, ledger, 100.0)
    state.ledger_configs[ledger.ledger] = LedgerConfig(margin_mode="auto", margin_call_mode="warn")
    event_time = pd.Timestamp("2026-03-10 14:39:00.000000002", tz="Asia/Shanghai")
    ctx = FlowContext(
        timestamp=event_time,
        event_queue=EventQueue(),
        active_ledgers=frozenset({ledger.ledger}),
        drafts_by_ledger={
            ledger.ledger: [EventDraft(
                EventKind.LEDGER,
                event_time,
                payload={"kind": "margin_check", "ledger_id": ledger.ledger_id},
                ledger=ledger.ledger,
            )],
        },
    )
    # Margin was opened at 10.  Neither a later close nor a settlement from
    # another contract may rewrite the actual fill basis used for margin.
    ctx.set(MarketDataModule.current_market_snapshot, {
        "settlement": {product: 99.0, other_product: 9.0},
        "close": {product: 12.0},
    })
    ctx.set(MarketDataModule.current_historical_fields, {
        product: {
            "VolumeMultiple": 10.0,
            "LongMarginRatioByMoney": 0.1,
        }
    })

    _apply_margin_requirement_change(state, ctx)

    entry = ledger.get(_positions_ref())[product]
    assert entry.margin_reserved is not None
    assert entry.margin_reserved.to_major() == pytest.approx(20.0)
    assert ledger.get(MarginModule.margin_requirement) == pytest.approx(20.0)
    assert _pool_valuation_prices(
        ctx, [ledger], LedgerModule, MarketDataModule,
    ) == {product: 12.0}
    assert ledger.get(MarginModule.margin_utilization) == pytest.approx(20.0 / 102.0)


def test_margin_liquidation_trade_intent_generates_order_only_in_trade_intent_layer():
    product = _product()
    strategy = Strategy(alias="S")
    ledger = LedgerState(strategy=strategy, base_currency="CNY")
    ledger.set(_positions_ref(), {
        product: ProductPosition(
            quantity=2.0,
            lots=deque([Lot(quantity=2.0, entry_price=10.0, multiplier=10.0, is_today=False)]),
            margin_reserved=DataMoney.from_major(12.0, currency="CNY", use_minor_units=False),
        )
    })
    state = BacktestRunState(
        strategy_configs={strategy: StrategyConfig(strategy=strategy, field_values={EngineModule.engine_mode: "auto"})},
        ledgers={f"private:{strategy.alias}": ledger},
    )
    _set_cash(state, ledger, 0.0)
    state.ledger_configs[ledger.ledger] = LedgerConfig(
        margin_mode="auto",
        margin_call_mode="liquidate",
        liquidation_target_buffer=0.0,
    )
    event_time = pd.Timestamp("2026-03-10 15:00:00.000000003", tz="Asia/Shanghai")
    market_time = event_time.floor("min")
    next_market_time = market_time + pd.Timedelta(minutes=1)
    state.market_data_store.current_prices_table = pd.DataFrame(
        {product: [12.0, 12.5]},
        index=pd.DatetimeIndex([market_time, next_market_time]),
    )
    state.market_data_store.market_price_tables = {
        "open": pd.DataFrame(
            {product: [11.5, 12.25]},
            index=pd.DatetimeIndex([market_time, next_market_time]),
        ),
    }
    queue = EventQueue()
    ctx = FlowContext(
        timestamp=event_time,
        event_queue=queue,
        active_ledgers=frozenset({ledger.ledger}),
        drafts_by_ledger={
            ledger.ledger: [EventDraft(
                EventKind.TRADE_INTENT,
                event_time,
                payload={"kind": "margin_liquidation", "ledger_id": ledger.ledger_id, "deficit": 12.0},
                ledger=ledger.ledger,
            )],
        },
    )
    ctx.set(MarketDataModule.current_market_snapshot, {"settlement": {product: 12.0}, "close": {product: 12.0}})
    ctx.set(MarketDataModule.current_historical_fields, {
        product: {
            "VolumeMultiple": 10.0,
            "LongMarginRatioByMoney": 0.1,
        }
    })

    _handle_margin_liquidation_notice(state, ctx)

    assert queue.pending_count_by_kind(EventKind.ORDER) == 1
    assert len(state.order_store.attempts_by_id) == 1


def test_margin_requirement_respects_strategy_book_cash_reserve_ratio():
    product = _product()
    strategy = Strategy(alias="S")
    ledger = LedgerState(strategy=strategy, base_currency="CNY")
    ledger.set(_positions_ref(), {
        product: ProductPosition(
            quantity=2.0,
            lots=deque([Lot(quantity=2.0, entry_price=10.0, multiplier=10.0, is_today=False)]),
            margin_reserved=DataMoney.from_major(2.0, currency="CNY", use_minor_units=False),
        )
    })
    state = BacktestRunState(
        strategy_configs={strategy: StrategyConfig(strategy=strategy, field_values={EngineModule.engine_mode: "auto"})},
        ledgers={f"private:{strategy.alias}": ledger},
    )
    _set_cash(state, ledger, 30.0)
    state.ledger_configs[ledger.ledger] = LedgerConfig(
        margin_mode="auto",
        margin_call_mode="warn",
        cash_reserve_ratio=0.5,
    )
    event_time = pd.Timestamp("2026-03-10 15:00:00.000000002", tz="Asia/Shanghai")
    ctx = FlowContext(
        timestamp=event_time,
        event_queue=EventQueue(),
        active_ledgers=frozenset({ledger.ledger}),
        drafts_by_ledger={
            ledger.ledger: [EventDraft(
                EventKind.LEDGER,
                event_time,
                payload={"kind": "margin_check", "ledger_id": ledger.ledger_id},
                ledger=ledger.ledger,
            )],
        },
    )
    ctx.set(MarketDataModule.current_market_snapshot, {"settlement": {product: 12.0}, "close": {product: 12.0}})
    ctx.set(MarketDataModule.current_historical_fields, {
        product: {
            "VolumeMultiple": 10.0,
            "LongMarginRatioByMoney": 0.1,
        }
    })

    _apply_margin_requirement_change(state, ctx)

    entry = ledger.get(_positions_ref())[product]
    assert _cash_major(state, ledger) == pytest.approx(15.0)
    assert entry.margin_reserved.to_major() == pytest.approx(17.0)
    assert ledger.get(MarginModule.margin_deficit) == pytest.approx(7.2)


def test_daily_mark_to_market_settlement_keeps_today_marker_absent_when_fee_mode_does_not_need_split():
    product = _product()
    strategy = Strategy(alias="S")
    config = StrategyConfig(
        strategy=strategy,
        active_flow_names=frozenset({"apply_daily_mark_to_market"}),
        field_values={
            EngineModule.engine_mode: "custom",
            TradingRuleModule.accounting_mode: "Custom",
            TradingRuleModule.cost_basis_method: "FIFO",
            TradingRuleModule.daily_mark_to_market_enabled: True,
            FeeModule.fee_mode: "zero",
            MarginModule.margin_mode: "auto",
        },
    )
    ledger = LedgerState(strategy=strategy, base_currency="CNY")
    ledger.set(_positions_ref(), {
        product: ProductPosition(
            quantity=2.0,
            lots=deque([
                Lot(quantity=1.0, entry_price=20.0, multiplier=1.0, is_today=None),
                Lot(quantity=1.0, entry_price=10.0, multiplier=1.0, is_today=None),
            ]),
            settlement_price=20.0,
            margin_reserved=DataMoney.from_major(4.0, currency="CNY", use_minor_units=False),
        )
    })
    account = BacktestRunState(strategy_configs={strategy: config}, ledgers={f"private:{strategy.alias}": ledger})
    _set_cash(account, ledger, 1000.0)
    account.ledger_configs[ledger.ledger] = _ledger_config(
        accounting_mode="Custom",
        cost_basis_method="FIFO",
        daily_mark_to_market_enabled=True,
        fee_mode="zero",
        margin_mode="auto",
    )
    ctx = FlowContext(
        timestamp=pd.Timestamp("2026-03-10 15:00:00.000000001", tz="Asia/Shanghai"),
        event_queue=EventQueue(),
        active_strategies=frozenset({strategy}),
    )
    ctx.set(MarketDataModule.current_market_snapshot, {"settlement": {product: 18.0}, "close": {product: 18.0}})
    ctx.set(MarketDataModule.current_historical_fields, {
        product: {
            "VolumeMultiple": 1.0,
            "SettlementPrice": 18.0,
            "LongMarginRatioByMoney": 0.1,
        }
    })

    _apply_daily_mark_to_market(account, ctx)

    entry = ledger.get(_positions_ref())[product]
    assert [(lot.quantity, lot.entry_price, lot.is_today) for lot in entry.lots] == [(2.0, 18.0, None)]


def test_daily_mark_to_market_close_uses_fifo_mark_to_market_lots():
    product = _product()
    config = _config(
        engine_mode="custom",
        accounting_mode="Custom",
        cost_basis_method="FIFO",
        daily_mark_to_market_enabled=True,
    )
    ledger_config = _ledger_config(
        accounting_mode="Custom",
        cost_basis_method="FIFO",
        daily_mark_to_market_enabled=True,
    )
    ledger = LedgerState(strategy=config.strategy, base_currency="CNY")
    ledger.set(
        _positions_ref(),
        {
            product: ProductPosition(
                quantity=2.0,
                lots=deque([
                    Lot(quantity=1.0, entry_price=20.0, multiplier=1.0, is_today=False),
                    Lot(quantity=1.0, entry_price=10.0, multiplier=1.0, is_today=True),
                ]),
                settlement_price=20.0,
                margin_reserved=DataMoney.from_major(4.0, currency="CNY", use_minor_units=False),
            )
        },
    )

    realized = close_position(
        ledger,
        config,
        product,
        quantity=1.0,
        fill_price=18.0,
        multiplier=1.0,
        ledger_config=ledger_config,
    )

    # Daily mark-to-market is not a blended average-cost close. It consumes
    # yesterday's lot first here, so closing at 18 against yesterday's 20 basis
    # realizes -2; today's @10 lot remains open.
    assert realized.to_major() == pytest.approx(18.0 - 20.0)
    entry = ledger.get(_positions_ref())[product]
    assert [lot.entry_price for lot in entry.lots] == [10.0]


def test_mark_to_market_requires_ffilled_price_for_held_position():
    product = _product()
    strategy = Strategy(alias="S")
    config = StrategyConfig(
        strategy=strategy,
        field_values={
            EngineModule.engine_mode: "auto",
            TradingRuleModule.accounting_mode: "Auto",
        },
    )
    ledger = LedgerState(strategy=strategy, base_currency="CNY")
    ledger.set(_positions_ref(), {
        product: ProductPosition(
            quantity=1.0,
            lots=deque([Lot(quantity=1.0, entry_price=10.0, multiplier=1.0, is_today=False)]),
            margin_reserved=DataMoney.from_major(1.0, currency="CNY", use_minor_units=False),
        )
    })

    with pytest.raises(KeyError, match="current price missing for held product"):
        mark_to_market(
            ledger,
            config,
            {},
            {product: {"SettlementPrice": 10.0, "VolumeMultiple": 1.0}},
            ledger_config=_ledger_config(accounting_mode="Auto"),
        )


def test_daily_mark_to_market_intraday_equity_uses_last_settlement_basis():
    product = _product()
    strategy = Strategy(alias="S")
    config = StrategyConfig(
        strategy=strategy,
        field_values={
            EngineModule.engine_mode: "auto",
            TradingRuleModule.accounting_mode: "Auto",
        },
    )
    ledger = LedgerState(strategy=strategy, base_currency="CNY")
    ledger.set(_positions_ref(), {
        product: ProductPosition(
            quantity=3.0,
            lots=deque([
                Lot(quantity=3.0, entry_price=12.0, multiplier=10.0, is_today=False),
            ]),
            settlement_price=12.0,
            margin_reserved=DataMoney.from_major(36.0, currency="CNY", use_minor_units=False),
        )
    })

    pnl = mark_to_market(
        ledger,
        config,
        {product: 13.5},
        {product: {"VolumeMultiple": 10.0, "SettlementPrice": 12.0}},
        ledger_config=_ledger_config(accounting_mode="Auto"),
    )

    assert pnl.to_major() == pytest.approx(3.0 * (13.5 - 12.0) * 10.0)


def test_daily_mark_to_market_defaults_to_aggregate_money_formula():
    product = _product()
    strategy = Strategy(alias="S")
    config = StrategyConfig(
        strategy=strategy,
        field_values={
            EngineModule.engine_mode: "auto",
            TradingRuleModule.accounting_mode: "Auto",
        },
    )
    ledger = LedgerState(strategy=strategy, base_currency="CNY")
    ledger.set(_positions_ref(), {
        product: ProductPosition(
            quantity=2.0,
            settlement_price=10.0,
            margin_reserved=DataMoney.from_major(0.0, currency="CNY", use_minor_units=True),
        )
    })

    pnl = mark_to_market(
        ledger,
        config,
        {product: 10.005},
        {product: {"VolumeMultiple": 1.0, "SettlementPrice": 10.005}},
        ledger_config=_ledger_config(accounting_mode="Auto"),
    )

    assert pnl.to_major() == pytest.approx(0.01)


def test_daily_mark_to_market_can_use_per_contract_price_point_policy():
    product = _product()
    strategy = Strategy(alias="S")
    config = StrategyConfig(
        strategy=strategy,
        field_values={
            EngineModule.engine_mode: "auto",
            TradingRuleModule.accounting_mode: "Auto",
        },
    )
    ledger = LedgerState(strategy=strategy, base_currency="CNY")
    ledger.set(_positions_ref(), {
        product: ProductPosition(
            quantity=2.0,
            settlement_price=10.0,
            margin_reserved=DataMoney.from_major(0.0, currency="CNY", use_minor_units=True),
        )
    })

    pnl = mark_to_market(
        ledger,
        config,
        {product: 10.005},
        {product: {
            "VolumeMultiple": 1.0,
            "SettlementPrice": 10.005,
            "MoneyCalculationPolicy": "per_contract_price_point",
        }},
        ledger_config=_ledger_config(accounting_mode="Auto"),
    )

    assert pnl.to_major() == pytest.approx(0.02)


def test_daily_mark_to_market_lot_positions_still_use_money_policy():
    product = _product()
    strategy = Strategy(alias="S")
    config = StrategyConfig(
        strategy=strategy,
        field_values={
            EngineModule.engine_mode: "auto",
            TradingRuleModule.accounting_mode: "Auto",
        },
    )
    ledger = LedgerState(strategy=strategy, base_currency="CNY")
    ledger.set(_positions_ref(), {
        product: ProductPosition(
            quantity=2.0,
            lots=deque([Lot(quantity=2.0, entry_price=10.0, multiplier=1.0, is_today=False)]),
            settlement_price=10.0,
            margin_reserved=DataMoney.from_major(0.0, currency="CNY", use_minor_units=True),
        )
    })

    pnl = mark_to_market(
        ledger,
        config,
        {product: 10.005},
        {product: {
            "VolumeMultiple": 1.0,
            "SettlementPrice": 10.005,
            "MoneyCalculationPolicy": "per_contract_price_point",
        }},
        ledger_config=_ledger_config(accounting_mode="Auto"),
    )

    assert pnl.to_major() == pytest.approx(0.02)


def test_daily_mark_to_market_equity_flow_includes_intraday_floating_pnl():
    from tools.testers.backtest.modules.ledger_module import LedgerModule, _basic_equity

    product = _product()
    strategy = Strategy(alias="S")
    config = StrategyConfig(
        strategy=strategy,
        field_values={
            EngineModule.engine_mode: "auto",
            TradingRuleModule.accounting_mode: "Auto",
        },
    )
    ledger = LedgerState(strategy=strategy, base_currency="CNY")
    ledger.set(_positions_ref(), {
        product: ProductPosition(
            quantity=3.0,
            lots=deque([
                Lot(quantity=3.0, entry_price=12.0, multiplier=10.0, is_today=False),
            ]),
            settlement_price=12.0,
            margin_reserved=DataMoney.from_major(36.0, currency="CNY", use_minor_units=False),
        )
    })
    account = BacktestRunState(strategy_configs={strategy: config}, ledgers={f"private:{strategy.alias}": ledger})
    _set_cash(account, ledger, 1000.0)
    account.ledger_configs[ledger.ledger] = _ledger_config(accounting_mode="Auto")
    ctx = FlowContext(
        timestamp=pd.Timestamp("2026-03-10 10:00:00", tz="Asia/Shanghai"),
        event_queue=EventQueue(),
        active_strategies=frozenset({strategy}),
    )
    ctx.set(MarketDataModule.current_prices, {product: 13.5})
    ctx.set(MarketDataModule.current_historical_fields, {
        product: {"VolumeMultiple": 10.0, "SettlementPrice": 12.0}
    })

    _basic_equity(account, ctx)

    assert ctx.get_for(LedgerModule.equity, strategy) == pytest.approx(1000.0 + 36.0 + 45.0)


def test_daily_mark_to_market_close_realizes_from_last_settlement_not_original_entry():
    product = _product()
    config = _config(
        engine_mode="custom",
        accounting_mode="Custom",
        cost_basis_method="FIFO",
        daily_mark_to_market_enabled=True,
    )
    ledger_config = _ledger_config(
        accounting_mode="Custom",
        cost_basis_method="FIFO",
        daily_mark_to_market_enabled=True,
    )
    ledger = LedgerState(strategy=config.strategy, base_currency="CNY")
    ledger.set(_positions_ref(), {
        product: ProductPosition(
            quantity=3.0,
            lots=deque([
                Lot(quantity=3.0, entry_price=12.0, multiplier=10.0, is_today=False),
            ]),
            settlement_price=12.0,
        )
    })

    realized = close_position(
        ledger, config, product, quantity=1.0, fill_price=13.5, multiplier=10.0,
        ledger_config=ledger_config,
    )

    assert realized.to_major() == pytest.approx((13.5 - 12.0) * 10.0)


def _positions_ref():
    from tools.testers.backtest.modules.ledger_module import LedgerModule
    return LedgerModule.positions


def _cash_ref():
    return CashPoolModule.cash
