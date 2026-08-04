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
    _schedule_margin_check_notices,
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


def _context(state, strategy, ledger, kind, *, payload=None):
    timestamp = pd.Timestamp("2024-01-01 09:01")
    draft = EventDraft(kind, timestamp, strategy=strategy, ledger=ledger.ledger, payload=payload)
    kwargs = {"drafts_by_ledger": {ledger.ledger: [draft]}} if kind is EventKind.LEDGER else {
        "drafts_by_strategy": {strategy: [draft]},
    }
    queue = EventQueue()
    return queue, FlowContext(
        timestamp=timestamp,
        event_queue=queue,
        event_kind=kind,
        active_strategies=frozenset({strategy}),
        active_ledgers=frozenset({ledger.ledger}),
        **kwargs,
    )


def test_margin_check_guard_drops_only_inert_ledgers():
    state, _, ledger = _margin_state()
    draft = EventDraft(EventKind.LEDGER, pd.Timestamp("2024-01-01"), ledger=ledger.ledger)
    ledger.set(LedgerModule.positions, {})
    assert not _margin_check_should_dispatch(state, draft)
    ledger.set(MarginModule.margin_requirement, 1.0)
    assert _margin_check_should_dispatch(state, draft)


def test_initialization_registers_only_one_check_for_existing_position():
    state, strategy, _ = _margin_state()
    index = pd.date_range("2024-01-01 09:00", periods=3, freq="1min")
    state.market_data_store.publish_causal_valuation(pd.DataFrame({"P": [1.0, 2.0, 3.0]}, index=index))
    ctx = FlowContext(None, EventQueue(), active_strategies=frozenset({strategy}))
    _register_margin_check_notices(state, ctx)
    drafts = ctx.get(MarginModule.margin_check_events)
    assert len(drafts) == 1
    assert drafts[0].timestamp == index[0] + pd.Timedelta(nanoseconds=2)


def test_successful_fill_schedules_check_but_unfilled_order_does_not():
    state, strategy, ledger = _margin_state()
    empty_queue, empty_ctx = _context(state, strategy, ledger, EventKind.ORDER)
    _schedule_margin_check_notices(state, empty_ctx)
    assert empty_queue.pending_count() == 0

    queue, ctx = _context(state, strategy, ledger, EventKind.ORDER)
    ctx.set(LedgerModule._order_fill_valuation_prices_ref, {ledger.ledger_id: {"P": 2.0}})
    _schedule_margin_check_notices(state, ctx)
    draft = queue.snapshot_head(1)[0]
    assert queue.pending_count() == 1
    assert draft.ledger is ledger.ledger
    assert draft.timestamp == ctx.timestamp + pd.Timedelta(nanoseconds=1)


def test_only_margin_relevant_field_changes_schedule_check():
    state, strategy, ledger = _margin_state()

    def pending(fields):
        payload = {"kind": "field_change", "changes": {"P": fields}}
        queue, ctx = _context(state, strategy, ledger, EventKind.FIELD_CHANGE, payload=payload)
        _schedule_margin_check_notices(state, ctx)
        return queue.pending_count()

    assert pending({"LongMarginRatioByMoney": 0.12}) == 1
    assert pending({"OpenRatioByMoney": 2.0}) == 0


def test_dmtm_schedules_check_for_affected_ledger():
    state, strategy, ledger = _margin_state()
    payload = {"kind": "daily_mark_to_market", "ledger_id": ledger.ledger_id}
    queue, ctx = _context(state, strategy, ledger, EventKind.LEDGER, payload=payload)
    _schedule_margin_check_notices(state, ctx)
    draft = queue.snapshot_head(1)[0]
    assert queue.pending_count() == 1
    assert draft.ledger is ledger.ledger
    assert draft.payload["source"] == "ledger"
