import pandas as pd
from types import SimpleNamespace

from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.market_events import MarketFeedEvent, Quote
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.engines.native.strategy_hooks import StrategyContext
from tools.testers.backtest.engines.native.position_events import (
    PositionEventKind,
    position_events_for_fill,
)
from tools.testers.backtest.engines.native.position import ProductPosition
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.strategy_hooks import StrategyRuntime
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


class FilledStrategy(Strategy):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.seen: list[str] = []

    def on_order_filled(self, ctx, order):
        self.seen.append("on_order_filled")


class MutatingOrderStrategy(Strategy):
    def on_order_filled(self, ctx, order):
        order.status = OrderStatus.CANCELLED


class MutatingFeedStrategy(Strategy):
    def on_book_snapshot(self, ctx, snapshot):
        snapshot["bids"].append((1.0, 1.0))


class PositionStrategy(Strategy):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.position_kinds: list[PositionEventKind] = []

    def on_position_opened(self, ctx, position_event):
        self.position_kinds.append(position_event.kind)

    def on_position_closed(self, ctx, position_event):
        self.position_kinds.append(position_event.kind)


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
        "kind": "strategy_runtime_intent",
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
        "kind": "strategy_runtime_command",
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
        status=OrderStatus.SUBMITTED,
    )
    state = SimpleNamespace(order_store=OrderStore())
    state.order_store.register_order(order)
    payload = {
        "kind": "strategy_runtime_command",
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
    pending = ctx._event_queue.snapshot_head()
    assert len(pending) == 2
    assert [event.kind for event in pending] == [
        EventKind.ORDER_STATUS,
        EventKind.ORDER_STATUS,
    ]
    assert [event.payload.status for event in pending] == [
        OrderStatus.PENDING_CANCEL,
        OrderStatus.CANCELLED,
    ]
    assert all(event.payload is not order for event in pending)


def test_hook_replace_command_exposes_pending_replace_before_cancel():
    strategy = QuoteStrategy(alias="command-replace")
    order = Order(
        instrument="P1",
        timestamp=pd.Timestamp("2025-01-01"),
        quantity=2.0,
        intent_quantity=2.0,
        strategy=strategy,
        order_id="replace-me",
        status=OrderStatus.ACCEPTED,
    )
    state = SimpleNamespace(order_store=OrderStore())
    state.order_store.register_order(order)
    payload = {
        "kind": "strategy_runtime_command",
        "command_kind": "replace_order",
        "order_id": "replace-me",
        "quantity": 3.0,
        "reason": "resize",
    }
    event = EventDraft(EventKind.SIGNAL, pd.Timestamp("2025-01-01"), strategy, payload)
    ctx = _context(strategy, EventKind.SIGNAL, [event])

    from tools.testers.backtest.modules.strategy_hooks import _apply_signal_intent

    _apply_signal_intent(state, ctx)

    assert order.status is OrderStatus.CANCELLED
    pending = ctx._event_queue.snapshot_head()
    assert [event.payload.status for event in pending] == [
        OrderStatus.PENDING_UPDATE,
        OrderStatus.CANCELLED,
    ]


def test_terminal_order_cancel_is_a_noop_without_pending_status_event():
    strategy = QuoteStrategy(alias="terminal-cancel")
    order = Order(
        instrument="P1",
        timestamp=pd.Timestamp("2025-01-01"),
        quantity=2.0,
        intent_quantity=2.0,
        strategy=strategy,
        order_id="already-cancelled",
        status=OrderStatus.CANCELLED,
    )
    state = SimpleNamespace(order_store=OrderStore())
    state.order_store.register_order(order)
    payload = {
        "kind": "strategy_runtime_command",
        "command_kind": "cancel_order",
        "order_id": order.order_id,
        "reason": "repeat",
    }
    event = EventDraft(EventKind.SIGNAL, pd.Timestamp("2025-01-01"), strategy, payload)
    ctx = _context(strategy, EventKind.SIGNAL, [event])

    from tools.testers.backtest.modules.strategy_hooks import _apply_signal_intent

    _apply_signal_intent(state, ctx)

    assert ctx._event_queue.snapshot_head() == []


def test_custom_strategy_mode_selects_hooks_without_group_flows():
    active = _resolve_active_flow_names({"strategy_kind": "custom"})
    config = next(iter(build_strategy_configs({"custom": {"strategy_kind": "custom"}}).values()))

    assert "strategy_runtime_on_bar" in active
    assert "strategy_runtime_on_order_event" in config.active_flow_names
    assert "schedule_bar_events" in active
    assert "group_quantile_membership" not in active


def test_strategy_runtime_is_the_registered_strategy_module():
    assert StrategyRuntime.key == "strategy_runtime"


def test_order_status_event_is_an_isolated_lifecycle_snapshot():
    from tools.testers.backtest.modules.order_lifecycle import order_status_event

    strategy = Strategy(alias="status-snapshot")
    order = Order(
        instrument="P1",
        timestamp=pd.Timestamp("2025-01-01"),
        quantity=1.0,
        intent_quantity=1.0,
        strategy=strategy,
        status=OrderStatus.SUBMITTED,
    )
    event = order_status_event(order, timestamp=order.timestamp)
    order.status = OrderStatus.ACCEPTED

    assert event.kind is EventKind.ORDER_STATUS
    assert event.payload.status is OrderStatus.SUBMITTED


def test_order_matching_axis_does_not_duplicate_status_axis_callback():
    strategy = FilledStrategy(alias="deduplicated-order-hook")
    config = type("ConfigView", (), {
        "uses_flow": lambda self, name: name == "strategy_runtime_on_order_status_event",
    })()
    state = type("StateView", (), {
        "config_for": lambda self, _strategy: config,
    })()
    order = type("OrderView", (), {"status": OrderStatus.FILLED})()
    event = EventDraft(EventKind.ORDER, pd.Timestamp("2025-01-01"), strategy, order)
    matching_ctx = _context(strategy, EventKind.ORDER, [event])

    from tools.testers.backtest.modules.strategy_hooks.dispatch import (
        _call_order_event,
        _call_order_status_event,
    )

    _call_order_event(state, matching_ctx)
    assert strategy.seen == []

    status_ctx = _context(
        strategy, EventKind.ORDER_STATUS,
        [EventDraft(EventKind.ORDER_STATUS, pd.Timestamp("2025-01-01"), strategy, order)],
    )
    _call_order_status_event(state, status_ctx)
    assert strategy.seen == ["on_order_filled"]


def test_internal_pending_conflict_cancel_emits_status_snapshot():
    from tools.testers.backtest.modules.group.execution import apply_pending_conflict

    strategy = Strategy(alias="pending-conflict")
    stale = Order(
        instrument="P1", timestamp=pd.Timestamp("2025-01-01"),
        quantity=1.0, intent_quantity=1.0, strategy=strategy,
        order_id="stale", status=OrderStatus.ACCEPTED,
    )
    stale.set("price_timestamp", pd.Timestamp("2025-01-01 09:01"))
    state = SimpleNamespace(
        order_store=OrderStore(),
        config_for=lambda _strategy: type(
            "ConfigView", (), {
                "uses_flow": lambda self, name: name == "strategy_runtime_on_order_status_event",
            },
        )(),
    )
    state.order_store.register_order(stale)
    pending = {(strategy, "P1"): stale}

    event = apply_pending_conflict(
        state, strategy, stale, pd.Timestamp("2025-01-01 09:00"),
        pending, conflict=None,
    )

    assert event
    assert [item.kind for item in event] == [EventKind.ORDER_STATUS, EventKind.ORDER_STATUS]
    assert [item.payload.status for item in event] == [
        OrderStatus.PENDING_CANCEL,
        OrderStatus.CANCELLED,
    ]


def test_blocked_order_status_is_emitted_once_by_execution_scheduler():
    from tools.testers.backtest.modules.group.execution import schedule_order_execution
    from tools.testers.backtest.modules.group_membership import GroupMembershipModule
    from tools.testers.backtest.modules.order_construct import OrderConstructModule

    strategy = Strategy(alias="blocked-order")
    order = Order(
        instrument="P1", timestamp=pd.Timestamp("2025-01-01"),
        quantity=1.0, intent_quantity=1.0, strategy=strategy,
        order_id="blocked", status=OrderStatus.BLOCKED,
    )
    config = type("ConfigView", (), {
        "get": lambda self, _ref, default=None: default,
        "uses_flow": lambda self, name: name == "strategy_runtime_on_order_status_event",
    })()
    state = SimpleNamespace(
        order_store=OrderStore(),
        config_for=lambda _strategy: config,
        market_data_store=SimpleNamespace(trading_day_resolver=None),
    )
    # The blocked branch is reached before schedule lookup; only these fields
    # are needed to prove that it emits once and remains local to execution.
    ctx = _context(strategy, EventKind.SIGNAL, [])
    ctx.active_strategies = frozenset({strategy})
    ctx.set_for(OrderConstructModule.orders, strategy, [order])
    state.order_store.pending_orders = {}

    # The complete scheduler needs execution settings for non-blocked orders;
    # call twice with the same object to test the one-shot marker.
    schedule_order_execution(state, ctx)
    first = ctx._event_queue.snapshot_head()
    schedule_order_execution(state, ctx)
    second = ctx._event_queue.snapshot_head()

    assert [event.payload.status for event in first] == [OrderStatus.BLOCKED]
    assert [event.payload.status for event in second] == [OrderStatus.BLOCKED]


def test_partial_fill_uses_specific_order_hook():
    strategy = PartialStrategy(alias="partial-hook")
    order = type("OrderView", (), {"status": OrderStatus.PARTIALLY_FILLED})()

    from tools.testers.backtest.modules.strategy_hooks.dispatch import _specific_order_hook

    _specific_order_hook(strategy, StrategyContext(strategy, None, EventKind.ORDER, {}, {}), order)

    assert strategy.seen == ["partial"]


def test_position_event_dispatch_uses_specific_hook_after_fill():
    strategy = PositionStrategy(alias="position-hook")
    event = position_events_for_fill(
        product="P1", previous_quantity=0.0, quantity=2.0,
        price=10.0, order_id="o1", fill_id="f1", ledger_id="l1",
    )[0]
    ctx = _context(
        strategy, EventKind.POSITION,
        [EventDraft(EventKind.POSITION, pd.Timestamp("2025-01-01"), strategy, event)],
    )

    from tools.testers.backtest.modules.strategy_hooks import _call_position_event

    _call_position_event(object(), ctx)

    assert strategy.position_kinds == [PositionEventKind.OPENED]


def test_position_sign_flip_is_close_then_open():
    events = position_events_for_fill(
        product="P1", previous_quantity=2.0, quantity=-1.0,
        price=10.0, order_id="o1", fill_id="f1", ledger_id="l1",
    )

    assert [event.kind for event in events] == [
        PositionEventKind.CLOSED,
        PositionEventKind.OPENED,
    ]
    assert [(event.previous_quantity, event.quantity) for event in events] == [
        (2.0, 0.0),
        (0.0, -1.0),
    ]


def test_strategy_context_positions_are_detached_snapshots():
    strategy = PositionStrategy(alias="position-snapshot")
    product = "P1"
    source = ProductPosition(quantity=3.0)
    ledger = type("LedgerView", (), {
        "get": lambda self, ref, default=None: {
            LedgerModule.positions: {product: source},
        }.get(ref, default),
    })()
    state = type("StateView", (), {
        "ledger_for_strategy": lambda self, _strategy: ledger,
    })()
    ctx = _context(strategy, EventKind.POSITION, [])

    from tools.testers.backtest.modules.strategy_hooks.dispatch import _context_for

    view = _context_for(state, ctx, strategy)
    view.positions[product].quantity = 99.0

    assert source.quantity == 3.0


def test_order_callbacks_receive_detached_order_snapshots():
    strategy = MutatingOrderStrategy(alias="order-snapshot")
    order = Order(
        instrument="P1", timestamp=pd.Timestamp("2025-01-01"),
        quantity=1.0, intent_quantity=1.0, strategy=strategy,
        status=OrderStatus.FILLED,
    )
    ctx = _context(
        strategy, EventKind.ORDER,
        [EventDraft(EventKind.ORDER, pd.Timestamp("2025-01-01"), strategy, order)],
    )

    from tools.testers.backtest.modules.strategy_hooks import _call_order_event

    _call_order_event(object(), ctx)

    assert order.status is OrderStatus.FILLED


def test_feed_callbacks_receive_detached_mutable_payload_snapshots():
    strategy = MutatingFeedStrategy(alias="feed-snapshot")
    payload = {"bids": [], "asks": []}
    event = MarketFeedEvent(
        pd.Timestamp("2025-01-01"), "P1", "book_snapshot", payload,
    )
    ctx = _context(
        strategy, EventKind.MARKET_FEED,
        [EventDraft(EventKind.MARKET_FEED, event.timestamp, strategy, event)],
    )

    from tools.testers.backtest.modules.strategy_hooks import _call_market_feed

    _call_market_feed(object(), ctx)

    assert payload["bids"] == []
