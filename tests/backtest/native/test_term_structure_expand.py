from __future__ import annotations

from tools.testers.backtest.engines.native.ledger import BacktestRunState, StrategyConfig
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.product_selection import ProductSelectionModule, _expand_term_structure


def test_expand_is_identity_for_non_term_structure_products():
    s = Strategy(alias="S")
    account = BacktestRunState(strategy_configs={s: StrategyConfig(strategy=s)})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s, frozenset({"P1", "P2"}))
    _expand_term_structure(account, ctx)
    assert ctx.get_for(ProductSelectionModule.products, s) == frozenset({"P1", "P2"})
