from __future__ import annotations

import pandas as pd

from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.engines.native.ledger import AccountState, StrategyConfig
from tools.testers.backtest.engines.native.order import Order, OrderStatus
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowRegistry, run
from tools.testers.backtest.engines.native.strategy import Strategy


def _account(strategies, active_flow_names=frozenset()):
    configs = {
        s: StrategyConfig(strategy=s, active_flow_names=active_flow_names)
        for s in strategies
    }
    return AccountState(strategy_configs=configs)


def test_empty_flows_runs_without_error():
    queue = EventQueue()
    account = _account([])
    run(account, queue, [])


def test_pre_replay_flow_produces_event_processed_by_per_event_flow():
    s = Strategy(alias="S")
    seen = []

    def emit_signal(account, ctx) -> None:
        ctx.set(SIG_REF, EventDraft(EventKind.SIGNAL, pd.Timestamp("2024-01-01"), s))

    def handle_signal(account, ctx) -> None:
        seen.append(ctx.timestamp)

    from tools.testers.backtest.modules.base import FieldRef
    global SIG_REF
    SIG_REF = FieldRef("sig", owner="X")

    f_emit = Flow("emit_signal", inputs=(), outputs=(), phase=Phase.PRE_REPLAY, compute=emit_signal)
    f_handle = Flow(
        "handle_signal", inputs=(), outputs=(), phase=Phase.PER_EVENT,
        event_kind=EventKind.SIGNAL, compute=handle_signal,
    )

    registry = FlowRegistry()
    registry.register_flow(f_emit)
    registry.register_flow(f_handle)

    account = _account([s], active_flow_names=frozenset({"handle_signal"}))
    queue = EventQueue()
    run(account, queue, registry.resolve())

    assert seen == [pd.Timestamp("2024-01-01")]


def test_chained_event_production_is_consumed_not_dropped():
    s = Strategy(alias="S")
    fills: list[str] = []

    order = Order(
        instrument="P1", timestamp=pd.Timestamp("2024-01-01"),
        quantity=1.0, intent_quantity=1.0, strategy=s, status=OrderStatus.SCHEDULED,
    )

    def emit_signal(account, ctx) -> None:
        ctx.set(SIG_REF2, EventDraft(EventKind.SIGNAL, pd.Timestamp("2024-01-01"), s))

    def on_signal_emit_order(account, ctx) -> None:
        fills.append("signal")
        ctx.set(SIG_REF2, EventDraft(EventKind.ORDER, pd.Timestamp("2024-01-02"), s, order))

    def on_order(account, ctx) -> None:
        fills.append("order")

    from tools.testers.backtest.modules.base import FieldRef
    global SIG_REF2
    SIG_REF2 = FieldRef("sig2", owner="X")

    f_emit = Flow("emit_signal2", inputs=(), outputs=(), phase=Phase.PRE_REPLAY, compute=emit_signal)
    f_on_signal = Flow(
        "on_signal", inputs=(), outputs=(), phase=Phase.PER_EVENT,
        event_kind=EventKind.SIGNAL, compute=on_signal_emit_order,
    )
    f_on_order = Flow(
        "on_order", inputs=(), outputs=(), phase=Phase.PER_EVENT,
        event_kind=EventKind.ORDER, compute=on_order,
    )

    registry = FlowRegistry()
    registry.register_flow(f_emit)
    registry.register_flow(f_on_signal)
    registry.register_flow(f_on_order)

    account = _account([s], active_flow_names=frozenset({"on_signal", "on_order"}))
    queue = EventQueue()
    run(account, queue, registry.resolve())

    assert fills == ["signal", "order"]


def test_dispatch_grouped_by_active_flow_names():
    s1, s2 = Strategy(alias="A"), Strategy(alias="B")
    seen_ctx = {}

    def f1_compute(account, ctx) -> None:
        seen_ctx["f1"] = frozenset(ctx.active_strategies)

    def f2_compute(account, ctx) -> None:
        seen_ctx["f2"] = frozenset(ctx.active_strategies)

    f1 = Flow("f1", inputs=(), outputs=(), phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL, compute=f1_compute)
    f2 = Flow("f2", inputs=(), outputs=(), phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL, compute=f2_compute)

    registry = FlowRegistry()
    registry.register_flow(f1)
    registry.register_flow(f2)

    configs = {
        s1: StrategyConfig(strategy=s1, active_flow_names=frozenset({"f1"})),
        s2: StrategyConfig(strategy=s2, active_flow_names=frozenset({"f2"})),
    }
    account = AccountState(strategy_configs=configs)
    queue = EventQueue()

    t = pd.Timestamp("2024-01-01")

    resolved = registry.resolve()
    from tools.testers.backtest.engines.native.scheduler import sort_and_validate, make_dispatcher
    groups = sort_and_validate(resolved)
    dispatcher = make_dispatcher(groups[(Phase.PER_EVENT, EventKind.SIGNAL)], account, queue)
    dispatcher([EventDraft(EventKind.SIGNAL, t, s1), EventDraft(EventKind.SIGNAL, t, s2)])

    assert seen_ctx["f1"] == frozenset({s1})
    assert seen_ctx["f2"] == frozenset({s2})


def test_flow_not_applicable_to_any_strategy_is_skipped():
    s1 = Strategy(alias="A")
    called = []

    f1 = Flow("f1", inputs=(), outputs=(), phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL,
              compute=lambda a, c: called.append(True))

    registry = FlowRegistry()
    registry.register_flow(f1)
    configs = {s1: StrategyConfig(strategy=s1, active_flow_names=frozenset())}
    account = AccountState(strategy_configs=configs)
    queue = EventQueue()

    from tools.testers.backtest.engines.native.scheduler import sort_and_validate, make_dispatcher
    groups = sort_and_validate(registry.resolve())
    dispatcher = make_dispatcher(groups[(Phase.PER_EVENT, EventKind.SIGNAL)], account, queue)
    dispatcher([EventDraft(EventKind.SIGNAL, pd.Timestamp("2024-01-01"), s1)])

    assert called == []


def test_strategy_scoped_pre_replay_flow_is_skipped_when_no_strategy_uses_it():
    s = Strategy(alias="S")
    called: list[str] = []

    scoped = Flow(
        "scoped_pre", inputs=(), outputs=(), phase=Phase.PRE_REPLAY,
        compute=lambda account, ctx: called.append("scoped"),
        strategy_scoped=True,
    )
    global_flow = Flow(
        "global_pre", inputs=(), outputs=(), phase=Phase.PRE_REPLAY,
        compute=lambda account, ctx: called.append("global"),
    )

    registry = FlowRegistry()
    registry.register_flow(scoped)
    registry.register_flow(global_flow)
    account = _account([s], active_flow_names=frozenset())

    run(account, EventQueue(), registry.resolve())

    assert called == ["global"]


def test_strategy_scoped_pre_replay_flow_runs_for_applicable_strategies():
    s1, s2 = Strategy(alias="A"), Strategy(alias="B")
    active_seen: list[frozenset[Strategy]] = []

    scoped = Flow(
        "scoped_pre", inputs=(), outputs=(), phase=Phase.PRE_REPLAY,
        compute=lambda account, ctx: active_seen.append(ctx.active_strategies),
        strategy_scoped=True,
    )

    registry = FlowRegistry()
    registry.register_flow(scoped)
    account = AccountState(strategy_configs={
        s1: StrategyConfig(strategy=s1, active_flow_names=frozenset({"scoped_pre"})),
        s2: StrategyConfig(strategy=s2, active_flow_names=frozenset()),
    })

    run(account, EventQueue(), registry.resolve())

    assert active_seen == [frozenset({s1})]


def test_make_dispatcher_processes_all_drafts_for_one_strategy_in_one_batch():
    """Regression: previously drafts_by_strategy was dict[Strategy, EventDraft]
    (one per strategy), so a batch with several drafts for the SAME
    strategy silently dropped all but the last. payloads_for must surface
    every one of them."""
    s = Strategy(alias="S")
    seen_payloads: list[list] = []

    f1 = Flow(
        "f1", inputs=(), outputs=(), phase=Phase.PER_EVENT, event_kind=EventKind.ORDER,
        compute=lambda account, ctx: seen_payloads.append(list(ctx.payloads_for(s))),
    )
    registry = FlowRegistry()
    registry.register_flow(f1)
    account = _account([s], active_flow_names=frozenset({"f1"}))
    queue = EventQueue()

    t = pd.Timestamp("2024-01-01")
    payload1, payload2, payload3 = object(), object(), object()
    from tools.testers.backtest.engines.native.scheduler import make_dispatcher, sort_and_validate
    groups = sort_and_validate(registry.resolve())
    dispatcher = make_dispatcher(groups[(Phase.PER_EVENT, EventKind.ORDER)], account, queue)
    dispatcher([
        EventDraft(EventKind.ORDER, t, s, payload1),
        EventDraft(EventKind.ORDER, t, s, payload2),
        EventDraft(EventKind.ORDER, t, s, payload3),
    ])

    assert seen_payloads == [[payload1, payload2, payload3]]


def test_progress_fires_across_all_three_phases_with_description():
    s = Strategy(alias="S")
    seen: list[tuple[int, int, str]] = []

    pre = Flow(
        "pre_flow", inputs=(), outputs=(), phase=Phase.PRE_REPLAY,
        description="预处理", compute=lambda account, ctx: None,
    )
    post = Flow(
        "post_flow", inputs=(), outputs=(), phase=Phase.POST_REPLAY,
        compute=lambda account, ctx: None,  # no description -> falls back to name
    )
    on_signal = Flow(
        "on_signal", inputs=(), outputs=(), phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL,
        compute=lambda account, ctx: None,
    )

    registry = FlowRegistry()
    registry.register_flow(pre)
    registry.register_flow(post)
    registry.register_flow(on_signal)

    account = _account([s], active_flow_names=frozenset({"on_signal"}))
    queue = EventQueue()
    queue.push_event(EventDraft(EventKind.SIGNAL, pd.Timestamp("2024-01-01"), s))

    run(account, queue, registry.resolve(), progress=lambda completed, total, label: seen.append((completed, total, label)))

    labels = [label for _, _, label in seen]
    assert "预处理" in labels       # pre_flow's description
    assert "post_flow" in labels    # post's name (no description given)
    assert "on_signal" in labels
