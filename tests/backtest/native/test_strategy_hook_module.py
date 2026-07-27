import pandas as pd
from types import SimpleNamespace

from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.market_events import MarketFeedEvent, Quote
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.engines.native.strategy_hooks import StrategyContext
from tools.testers.backtest.modules.strategy_hooks import StrategyHookModule
from tools.testers.backtest.modules.target import TargetStrategyModule, OrderDeltaIntent
from tools.testers.backtest.engines.native.orders import Order, OrderStatus
from tools.testers.backtest.modules.order_lifecycle.store import OrderStore
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


class PartialStrategy(QuoteStrategy):
    def on_order_partially_filled(self, ctx, order):
        self.seen.append("partial")


def _context(strategy, event_kind, payloads):
    queue = EventQueue()
    return FlowContext(
        timestamp=pd.Timestamp("2025-01-01 09:00"),
        event_queue=queue,
        active_strategies=frozenset({strategy}),
        drafts_by_strategy={strategy: payloads},
        event_kind=event_kind,
    )


def test_market_feed_hook_emits_causal_signal():
    strategy = QuoteStrategy(alias="quote-hook")
    market_event = MarketFeedEvent(
        pd.Timestamp("2025-01-01 09:00"), "P1", "quote", Quote(10.0, 10.1),
    )
    ctx = _context(
        strategy,
        EventKind.MARKET_FEED,
        [EventDraft(EventKind.MARKET_FEED, market_event.timestamp, strategy, market_event)],
    )

    from tools.testers.backtest.modules.strategy_hooks import _call_market_feed

    _call_market_feed(object(), ctx)
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


def test_hook_submit_command_enters_existing_target_pipeline():
    strategy = QuoteStrategy(alias="command-adapter")
    payload = {
        "kind": "strategy_hook_command",
        "command_kind": "submit_order",
        "product": "P1",
        "quantity": 2.0,
        "side": "sell",
        "reason": "risk",
    }
    event = EventDraft(EventKind.SIGNAL, pd.Timestamp("2025-01-01"), strategy, payload)
    ctx = _context(strategy, EventKind.SIGNAL, [event])

    from tools.testers.backtest.modules.strategy_hooks import _apply_signal_intent

    _apply_signal_intent(SimpleNamespace(), ctx)

    intent = ctx.get_for(TargetStrategyModule.trade_intent, strategy)
    assert isinstance(intent, OrderDeltaIntent)
    assert intent.deltas == {"P1": -2.0}


def test_hook_cancel_command_closes_only_the_strategy_order():
    strategy = QuoteStrategy(alias="command-cancel")
    order = Order(
        instrument="P1",
        timestamp=pd.Timestamp("2025-01-01"),
        quantity=2.0,
        intent_quantity=2.0,
        strategy=strategy,
        order_id="cancel-me",
        status=OrderStatus.SCHEDULED,
    )
    state = SimpleNamespace(order_store=OrderStore())
    state.order_store.register_order(order)
    payload = {
        "kind": "strategy_hook_command",
        "command_kind": "cancel_order",
        "order_id": "cancel-me",
        "reason": "risk",
    }
    event = EventDraft(EventKind.SIGNAL, pd.Timestamp("2025-01-01"), strategy, payload)
    ctx = _context(strategy, EventKind.SIGNAL, [event])

    from tools.testers.backtest.modules.strategy_hooks import _apply_signal_intent

    _apply_signal_intent(state, ctx)

    assert order.status is OrderStatus.CANCELLED
    assert state.order_store.actions_by_order[order.order_id][0].reason == "risk"


def test_custom_strategy_mode_selects_hooks_without_group_flows():
    active = _resolve_active_flow_names({"strategy_kind": "custom"})
    config = next(iter(build_strategy_configs({"custom": {"strategy_kind": "custom"}}).values()))

    assert "strategy_hook_on_bar" in active
    assert "strategy_hook_on_order_event" in config.active_flow_names
    assert "schedule_bar_events" in active
    assert "group_quantile_membership" not in active


def test_partial_fill_uses_specific_order_hook():
    strategy = PartialStrategy(alias="partial-hook")
    order = type("OrderView", (), {"status": OrderStatus.PARTIALLY_FILLED})()

    from tools.testers.backtest.modules.strategy_hooks.dispatch import _specific_order_hook

    _specific_order_hook(strategy, StrategyContext(strategy, None, EventKind.ORDER, {}, {}), order)

    assert strategy.seen == ["partial"]
