from __future__ import annotations

import uuid

import pandas as pd

from tools.products.Product import Product
from tools.testers.backtest.engines.native.config import StrategyConfig
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.carry import CarryStrategyModule
from tools.testers.backtest.modules.carry_runtime import build_carry_targets
from tools.testers.backtest.modules.factor_signal import FactorSignalModule
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.product_selection import ProductSelectionModule
from tools.testers.backtest.modules.target import TargetStrategyModule


class TermProduct:
    def __init__(self, contracts):
        self.name = f"CARRY-{uuid.uuid4().hex}"
        self.contracts = contracts

    def get_term_structure_contracts(self, _day, depth=None):
        return self.contracts[:depth]

    def __str__(self):
        return self.name


def carry_state():
    strategy = Strategy(alias="carry")
    near, far = _contract(), _contract()
    product = TermProduct([near, far])
    config = StrategyConfig(strategy=strategy, field_values={
        TargetStrategyModule.strategy_kind: "carry",
        CarryStrategyModule.near_rank: 0,
        CarryStrategyModule.far_rank: 1,
        CarryStrategyModule.entry_threshold: 0.05,
        CarryStrategyModule.exit_threshold: 0.01,
        CarryStrategyModule.gross_weight: 1.0,
        LedgerModule.initial_capital_major: 100_000.0,
        LedgerModule.base_currency: "CNY",
    })
    state = BacktestRunState(strategy_configs={strategy: config})
    return state, strategy, product, near, far


def carry_target(
    state, strategy, product, near, far, timestamp, signal, prices=None,
):
    ctx = FlowContext(
        timestamp=pd.Timestamp(timestamp),
        event_queue=EventQueue(),
        active_strategies=frozenset({strategy}),
    )
    ctx.set_for(ProductSelectionModule.products, strategy, frozenset({product}))
    ctx.set_for(FactorSignalModule.signal_value, strategy, {product: signal})
    ctx.set(MarketDataModule.current_prices, prices or {near: 100.0, far: 90.0})
    ctx.set(MarketDataModule.current_tradable_status, {near: True, far: True})
    build_carry_targets(state, ctx, CarryStrategyModule)
    return ctx


def _contract() -> Product:
    return Product(
        name=f"LEG-{uuid.uuid4().hex}",
        point_value=1,
        currency="CNY",
    )
