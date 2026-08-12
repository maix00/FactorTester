from __future__ import annotations

import pandas as pd

from tools.data.types.data_money import DataMoney
from tools.products.Product import Product
from tools.testers.backtest.engines.native.config import LedgerConfig, StrategyConfig
from tools.testers.backtest.engines.native.ledger import ledger_identity
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.cash_pool import set_cash_for_ledger_pool
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.margin_budget import MarginBudgetModule
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.target import (
    PairedTargetWeightIntent,
    TargetStrategyModule,
)


def test_margin_budget_preserves_paired_intent_identity_and_policy():
    strategy = Strategy(alias="carry")
    near = Product(name="NEAR", point_value=1, currency="CNY")
    far = Product(name="FAR", point_value=1, currency="CNY")
    state = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(strategy=strategy),
    })
    ledger = state.ledger_for_strategy(strategy)
    state.ledger_configs[ledger_identity("private:carry")] = LedgerConfig(
        margin_mode="fixed",
        fixed_margin_ratio=0.10,
    )
    set_cash_for_ledger_pool(
        state,
        ledger,
        DataMoney.from_major(1_000.0, currency="CNY", use_minor_units=True),
    )
    ctx = FlowContext(
        timestamp=pd.Timestamp("2025-01-02 15:00"),
        event_queue=EventQueue(),
        active_strategies=frozenset({strategy}),
    )
    ctx.set_for(LedgerModule.equity, strategy, 1_000.0)
    ctx.set(MarketDataModule.current_prices, {near: 100.0, far: 100.0})
    ctx.set_for(
        MarketDataModule.current_historical_fields,
        strategy,
        {near: {}, far: {}},
    )
    original = PairedTargetWeightIntent(
        {near: 1.0, far: -1.0},
        reason="term_carry",
        parent_intent_id="pair-1",
        execution_policy="synchronized_submit",
    )
    ctx.set_for(TargetStrategyModule.trade_intent, strategy, original)
    ctx.set_for(TargetStrategyModule.target_weights, strategy, original.weights)

    MarginBudgetModule.apply_target_margin_budget.compute(state, ctx)

    scaled = ctx.get_for(TargetStrategyModule.trade_intent, strategy)
    assert isinstance(scaled, PairedTargetWeightIntent)
    assert scaled.parent_intent_id == "pair-1"
    assert scaled.execution_policy == "synchronized_submit"
    assert scaled.reason == "term_carry|margin_budget"
    assert scaled.weights[near] == -scaled.weights[far]
