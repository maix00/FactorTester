import pandas as pd

from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.market_events import MarketDataEvent, Quote
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.engines.native.strategy_hooks import StrategyContext
from tools.testers.backtest.modules.strategy_hooks import StrategyHookModule
from tools.testers.backtest.modules.target import TargetStrategyModule, OrderDeltaIntent
from tools.testers.backtest.engines.native.strategy_config_builder import _resolve_active_flow_names, build_strategy_configs


class QuoteStrategy(Strategy):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.seen: list[str] = []

    def on_start(self, ctx: StrategyContext):
        self.seen.append("start")

    def on_quote(self, ctx: StrategyContext, quote: Quote):
        self.seen.append(f"quote:{quote.bid_price}")
        return ctx.order_deltas({"P1": 1.0}, reason="quote-entry")

    def on_stop(self, ctx: StrategyContext):
        self.seen.append("stop")


def _context(strategy, event_kind, payloads):
    queue = EventQueue()
    return FlowContext(
        timestamp=pd.Timestamp("2025-01-01 09:00"),
        event_queue=queue,
        active_strategies=frozenset({strategy}),
        drafts_by_strategy={strategy: payloads},
        event_kind=event_kind,
    )


def test_market_data_hook_emits_causal_signal():
    strategy = QuoteStrategy(alias="quote-hook")
    market_event = MarketDataEvent(
        pd.Timestamp("2025-01-01 09:00"), "P1", "quote", Quote(10.0, 10.1),
    )
    ctx = _context(
        strategy,
        EventKind.MARKET_DATA,
        [EventDraft(EventKind.MARKET_DATA, market_event.timestamp, strategy, market_event)],
    )

    from tools.testers.backtest.modules.strategy_hooks import _call_market_data

    _call_market_data(object(), ctx)
    pending = ctx._event_queue.snapshot_head()

    assert strategy.seen == ["quote:10.0"]
    assert len(pending) == 1
    assert pending[0].kind is EventKind.SIGNAL
    assert pending[0].payload["intent_kind"] == "order_deltas"
    assert pending[0].payload["deltas"] == {"P1": 1.0}


def test_start_and_stop_are_lifecycle_only():
    strategy = QuoteStrategy(alias="lifecycle-hook")
    start_ctx = _context(strategy, None, [])
    stop_ctx = _context(strategy, None, [])

    from tools.testers.backtest.modules.strategy_hooks import _call_start, _call_stop

    _call_start(object(), start_ctx)
    _call_stop(object(), stop_ctx)

    assert strategy.seen == ["start", "stop"]


def test_hook_signal_intent_enters_existing_target_pipeline():
    strategy = QuoteStrategy(alias="intent-adapter")
    payload = {
        "kind": "strategy_hook_intent",
        "intent_kind": "order_deltas",
        "deltas": {"P1": 2.0},
        "reason": "test",
    }
    event = EventDraft(EventKind.SIGNAL, pd.Timestamp("2025-01-01"), strategy, payload)
    ctx = _context(strategy, EventKind.SIGNAL, [event])

    from tools.testers.backtest.modules.strategy_hooks import _apply_signal_intent

    _apply_signal_intent(object(), ctx)

    intent = ctx.get_for(TargetStrategyModule.trade_intent, strategy)
    assert isinstance(intent, OrderDeltaIntent)
    assert intent.deltas == {"P1": 2.0}


def test_custom_strategy_mode_selects_hooks_without_group_flows():
    active = _resolve_active_flow_names({"strategy_kind": "custom"})
    config = next(iter(build_strategy_configs({"custom": {"strategy_kind": "custom"}}).values()))

    assert "strategy_hook_on_bar" in active
    assert "strategy_hook_on_order_event" in config.active_flow_names
    assert "group_quantile_membership" not in active
