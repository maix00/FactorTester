from __future__ import annotations

from dataclasses import dataclass

from tools.testers.backtest.engines.native.ledger import AccountState, StrategyConfig
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.market_data import _check_market_data_coverage, _resolve_market_data_request
from tools.testers.backtest.modules.product_selection import ProductSelectionModule
from tools.data.types.time_freq import DataFreq


@dataclass(frozen=True)
class _Product:
    name: str

    def list_available_freqs(self):
        return [DataFreq.MIN1]


def test_market_data_coverage_uses_resolved_product_selection_context():
    strategy = Strategy(alias="A")
    selected = _Product("SELECTED")
    stale_request_product = _Product("STALE")
    account = AccountState(strategy_configs={strategy: StrategyConfig(strategy=strategy)})
    account.market_data_request = {"products": [stale_request_product]}
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, strategy, frozenset({selected}))

    _resolve_market_data_request(account, ctx)
    _check_market_data_coverage(account, ctx)

    assert getattr(account, "_market_data_load_plan") == [(selected, DataFreq.MIN1, None)]
