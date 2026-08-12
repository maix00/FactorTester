from __future__ import annotations

import pandas as pd

from tools.testers.backtest.engines.native.config import LedgerConfig, StrategyConfig
from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.ledger import LedgerState
from tools.testers.backtest.engines.native.position import ProductPosition
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.margin import (
    MarginModule,
    _margin_check_should_dispatch,
    _register_margin_check_notices,
)


def _margin_state() -> tuple[BacktestRunState, Strategy, LedgerState]:
    strategy = Strategy(alias="S")
    ledger = LedgerState(strategy=strategy, base_currency="CNY", ledger_id="private:S")
    ledger.set(LedgerModule.positions, {"P": ProductPosition(quantity=1.0)})
    state = BacktestRunState(
        strategy_configs={strategy: StrategyConfig(strategy=strategy)},
        ledgers={ledger.ledger: ledger},
    )
    state.ledger_configs[ledger.ledger] = LedgerConfig(
        margin_mode="fixed", margin_call_mode="liquidate",
    )
    return state, strategy, ledger


def test_margin_check_guard_drops_only_inert_ledgers():
    state, _, ledger = _margin_state()
    draft = EventDraft(EventKind.LEDGER, pd.Timestamp("2024-01-01"), ledger=ledger.ledger)
    ledger.set(LedgerModule.positions, {})
    assert not _margin_check_should_dispatch(state, draft)
    ledger.set(MarginModule.margin_requirement, 1.0)
    assert _margin_check_should_dispatch(state, draft)


def test_price_driven_margin_risk_keeps_each_market_timestamp():
    state, strategy, _ = _margin_state()
    index = pd.date_range("2024-01-01 09:00", periods=3, freq="1min")
    state.market_data_store.publish_causal_valuation(
        pd.DataFrame({"P": [1.0, 2.0, 3.0]}, index=index),
    )
    ctx = FlowContext(None, EventQueue(), active_strategies=frozenset({strategy}))
    _register_margin_check_notices(state, ctx)
    drafts = ctx.get(MarginModule.margin_check_events)
    assert len(drafts) == len(index)
    assert [draft.timestamp for draft in drafts] == [
        timestamp + pd.Timedelta(nanoseconds=2) for timestamp in index
    ]
    assert all(draft.dispatch_guard is _margin_check_should_dispatch for draft in drafts)
