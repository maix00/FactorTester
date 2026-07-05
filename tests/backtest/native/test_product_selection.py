from __future__ import annotations

from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.config import StrategyConfig
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.product_selection import ProductSelectionModule, _resolve_product_selection


class _FakeSelection:
    resolve_calls = 0

    def __init__(self, selection_id: str, products: frozenset) -> None:
        self.selection_id = selection_id
        self._products = products

    @property
    def products(self):
        type(self).resolve_calls += 1
        return self._products


def test_resolve_product_selection_dedups_by_selection_id():
    s1, s2, s3 = Strategy(alias="A"), Strategy(alias="B"), Strategy(alias="C")
    shared = _FakeSelection("sel-1", frozenset({"P1", "P2"}))
    other = _FakeSelection("sel-2", frozenset({"P3"}))

    configs = {
        s1: StrategyConfig(strategy=s1, field_values={ProductSelectionModule.product_path_selection: shared}),
        s2: StrategyConfig(strategy=s2, field_values={ProductSelectionModule.product_path_selection: shared}),
        s3: StrategyConfig(strategy=s3, field_values={ProductSelectionModule.product_path_selection: other}),
    }
    account = BacktestRunState(strategy_configs=configs)
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    _resolve_product_selection(account, ctx)

    assert ctx.get_for(ProductSelectionModule.products, s1) == frozenset({"P1", "P2"})
    assert ctx.get_for(ProductSelectionModule.products, s2) == frozenset({"P1", "P2"})
    assert ctx.get_for(ProductSelectionModule.products, s3) == frozenset({"P3"})
    # shared selection_id resolved once (1) + the other selection (1) = 2,
    # not 3 -- dedup by selection_id actually took effect, not coincidence
    assert _FakeSelection.resolve_calls == 2
