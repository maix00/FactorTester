from __future__ import annotations

import pandas as pd

from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.config import StrategyConfig
from tools.testers.backtest.engines.native.order import Order, OrderAttempt, OrderStatus
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowRegistry, run
from tools.testers.backtest.engines.native.strategy import Strategy


def _account(strategies, active_flow_names=frozenset()):
    configs = {
        s: StrategyConfig(strategy=s, active_flow_names=active_flow_names)
        for s in strategies
    }
    return BacktestRunState(strategy_configs=configs)


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

    account = _account([s], active_flow_names=frozenset({"emit_signal", "handle_signal"}))
    queue = EventQueue()
    run(account, queue, registry.resolve())

    assert seen == [pd.Timestamp("2024-01-01")]


def test_flow_profile_is_disabled_until_a_profiler_is_injected():
    s = Strategy(alias="S")

    def compute(account, ctx) -> None:
        return None

    flow = Flow("profiled_flow", inputs=(), outputs=(), phase=Phase.PRE_REPLAY, compute=compute)
    registry = FlowRegistry()
    registry.register_flow(flow)
    account = _account([s], active_flow_names=frozenset({"profiled_flow"}))

    run(account, EventQueue(), registry.resolve())

    rows = [row for row in account.runtime_info_rows if row.get("code") == "backtest_flow_profile"]
    assert rows == []


def test_injected_flow_profiler_records_slow_pre_replay_flow():
    from tools.testers.backtest.engines.native.profiling import CumulativeBacktestProfiler

    s = Strategy(alias="S")

    def compute(account, ctx) -> None:
        return None

    flow = Flow("profiled_flow", inputs=(), outputs=(), phase=Phase.PRE_REPLAY, compute=compute)
    registry = FlowRegistry()
    registry.register_flow(flow)
    account = _account([s], active_flow_names=frozenset({"profiled_flow"}))
    clock = iter((0.0, 0.0125))
    profiler = CumulativeBacktestProfiler(min_duration_ms=0.0, clock=lambda: next(clock))

    run(account, EventQueue(), registry.resolve(), profiler=profiler)

    rows = [row for row in account.runtime_info_rows if row.get("code") == "backtest_flow_profile"]
    assert len(rows) == 1
    assert rows[0]["details"]["phase"] == "pre_replay"
    assert rows[0]["details"]["flow"] == "profiled_flow"
    assert rows[0]["details"]["count"] == 1


def test_activity_sink_can_decline_payload_materialization() -> None:
    class ExpensiveFieldRef:
        @property
        def name(self):
            raise AssertionError("mode_info must not be materialized")

    class DecliningSink:
        def __init__(self) -> None:
            self.activities = []

        def wants_live_event(self, event: str) -> bool:
            return event != "activity"

        def emit_activity_manifest(self, phases) -> None:
            return None

        def emit_activity(self, **payload) -> None:
            self.activities.append(payload)

        def emit_signal_progress(self, **payload) -> None:
            return None

    s = Strategy(alias="S")
    flow = Flow(
        "declined_activity",
        inputs=(),
        outputs=(),
        phase=Phase.PRE_REPLAY,
        compute=lambda account, ctx: None,
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    account = _account([s], active_flow_names=frozenset({flow.name}))
    account.config_for(s).field_values[ExpensiveFieldRef()] = "unused"
    sink = DecliningSink()

    run(account, EventQueue(), registry.resolve(), activity_sink=sink)

    assert sink.activities == []


def test_flow_profile_reports_frequent_short_event_flow_after_replay(monkeypatch):
    from tools.testers.backtest.engines.native.profiling import CumulativeBacktestProfiler

    s = Strategy(alias="S")

    def emit_signals(account, ctx) -> None:
        ctx.set(
            PROFILE_SIG_REF,
            [
                EventDraft(EventKind.SIGNAL, pd.Timestamp(f"2024-01-01 09:0{minute}"), s)
                for minute in range(3)
            ],
        )

    def handle_signal(account, ctx) -> None:
        return None

    from tools.testers.backtest.modules.base import FieldRef
    global PROFILE_SIG_REF
    PROFILE_SIG_REF = FieldRef("profile_sig", owner="X")

    emit = Flow(
        "emit_profile_signals",
        inputs=(),
        outputs=(),
        phase=Phase.PRE_REPLAY,
        compute=emit_signals,
    )
    handle = Flow(
        "frequent_short_flow",
        inputs=(),
        outputs=(),
        phase=Phase.PER_EVENT,
        event_kind=EventKind.SIGNAL,
        compute=handle_signal,
    )
    registry = FlowRegistry()
    registry.register_flow(emit)
    registry.register_flow(handle)
    account = _account(
        [s],
        active_flow_names=frozenset({"emit_profile_signals", "frequent_short_flow"}),
    )
    clock = iter((0.0, 0.0, 1.0, 1.0004, 2.0, 2.0004, 3.0, 3.0004))
    profiler = CumulativeBacktestProfiler(min_duration_ms=1.0, clock=lambda: next(clock))

    run(account, EventQueue(), registry.resolve(), profiler=profiler)

    rows = [
        row
        for row in account.runtime_info_rows
        if row.get("code") == "backtest_flow_profile"
        and row.get("details", {}).get("flow") == "frequent_short_flow"
    ]
    assert len(rows) == 1
    assert rows[0]["details"]["count"] == 3
    assert rows[0]["details"]["total_ms"] == 1.2
    assert rows[0]["details"]["max_ms"] == 0.4


def test_chained_event_production_is_consumed_not_dropped():
    s = Strategy(alias="S")
    fills: list[str] = []

    order = Order(
        instrument="P1", timestamp=pd.Timestamp("2024-01-01"),
        quantity=1.0, intent_quantity=1.0, strategy=s, status=OrderStatus.SUBMITTED,
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

    account = _account([s], active_flow_names=frozenset({"emit_signal2", "on_signal", "on_order"}))
    queue = EventQueue()
    run(account, queue, registry.resolve())

    assert fills == ["signal", "order"]


def test_stale_order_attempt_is_skipped_before_order_flows_run():
    s = Strategy(alias="S")
    called: list[str] = []
    timestamp = pd.Timestamp("2024-01-02")
    order = Order(
        instrument="P1",
        timestamp=timestamp,
        quantity=1.0,
        intent_quantity=1.0,
        strategy=s,
        status=OrderStatus.SUBMITTED,
        order_id="O1",
    )
    attempt = OrderAttempt(
        attempt_id="A1",
        order_id=order.order_id,
        revision=order.revision,
        timestamp=timestamp,
        market_timestamp=timestamp,
        _order=order,
    )
    flow = Flow(
        "on_stale_order",
        inputs=(),
        outputs=(),
        phase=Phase.PER_EVENT,
        event_kind=EventKind.ORDER,
        compute=lambda _state, _ctx: called.append("order"),
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    account = _account([s], active_flow_names=frozenset({"on_stale_order"}))
    account.order_store.register_order(order)
    account.order_store.register_attempt(attempt)
    order.revision += 1

    from tools.testers.backtest.engines.native.scheduler import make_dispatcher, sort_and_validate

    flows = sort_and_validate(registry.resolve())[(Phase.PER_EVENT, EventKind.ORDER)]
    make_dispatcher(flows, account, EventQueue())([
        EventDraft(EventKind.ORDER, timestamp, s, attempt),
    ])

    assert called == []


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
    account = BacktestRunState(strategy_configs=configs)
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
    account = BacktestRunState(strategy_configs=configs)
    queue = EventQueue()

    from tools.testers.backtest.engines.native.scheduler import sort_and_validate, make_dispatcher
    groups = sort_and_validate(registry.resolve())
    dispatcher = make_dispatcher(groups[(Phase.PER_EVENT, EventKind.SIGNAL)], account, queue)
    dispatcher([EventDraft(EventKind.SIGNAL, pd.Timestamp("2024-01-01"), s1)])

    assert called == []


def test_pre_replay_flow_is_skipped_when_no_strategy_uses_it():
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

    assert called == []


def test_global_pre_replay_flow_runs_once_for_all_applicable_strategies():
    s1, s2 = Strategy(alias="A"), Strategy(alias="B")
    active_seen: list[frozenset[Strategy]] = []

    global_flow = Flow(
        "global_pre", inputs=(), outputs=(), phase=Phase.PRE_REPLAY,
        compute=lambda account, ctx: active_seen.append(ctx.active_strategies),
    )

    registry = FlowRegistry()
    registry.register_flow(global_flow)
    account = BacktestRunState(strategy_configs={
        s1: StrategyConfig(strategy=s1, active_flow_names=frozenset({"global_pre"})),
        s2: StrategyConfig(strategy=s2, active_flow_names=frozenset()),
    })

    run(account, EventQueue(), registry.resolve())

    assert active_seen == [frozenset({s1})]


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
    account = BacktestRunState(strategy_configs={
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


def test_make_dispatcher_filters_each_draft_with_its_domain_guard():
    """Event owners can reject inert notices before FlowContext construction."""
    strategy = Strategy(alias="S")
    seen_payloads: list[list[str]] = []
    flow = Flow(
        "guarded_flow",
        inputs=(),
        outputs=(),
        phase=Phase.PER_EVENT,
        event_kind=EventKind.LEDGER,
        compute=lambda account, ctx: seen_payloads.append(list(ctx.payloads_for(strategy))),
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    account = _account([strategy], active_flow_names=frozenset({"guarded_flow"}))
    timestamp = pd.Timestamp("2024-01-01")
    drafts = [
        EventDraft(
            EventKind.LEDGER,
            timestamp,
            strategy,
            payload="drop",
            dispatch_guard=lambda _state, draft: draft.payload == "keep",
        ),
        EventDraft(
            EventKind.LEDGER,
            timestamp,
            strategy,
            payload="keep",
            dispatch_guard=lambda _state, draft: draft.payload == "keep",
        ),
    ]

    from tools.testers.backtest.engines.native.scheduler import make_dispatcher, sort_and_validate

    groups = sort_and_validate(registry.resolve())
    make_dispatcher(groups[(Phase.PER_EVENT, EventKind.LEDGER)], account, EventQueue())(drafts)

    assert seen_payloads == [["keep"]]


def test_make_dispatcher_ledger_events_activate_exact_registered_strategies():
    """Ledger dispatch must match the old scan-all-strategies semantics.

    A cached ledger->strategy map is only a performance optimization; it must
    not change which strategies participate in ledger-scoped calculations.
    """
    from tools.testers.backtest.engines.native.ledger import ledger_identity
    from tools.testers.backtest.modules.strategy_book import strategy_book_store_for

    s1, s2, s3 = Strategy(alias="A"), Strategy(alias="B"), Strategy(alias="C")
    shared = ledger_identity("shared-book")
    other = ledger_identity("other-book")
    seen: list[frozenset] = []
    step_records: list[dict] = []

    flow = Flow(
        "ledger_flow", inputs=(), outputs=(), phase=Phase.PER_EVENT, event_kind=EventKind.LEDGER,
        compute=lambda account, ctx: seen.append(frozenset(ctx.active_strategies)),
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    account = _account([s1, s2, s3], active_flow_names=frozenset({"ledger_flow"}))
    store = strategy_book_store_for(account)
    store.register_strategy_ledgers(s1, (shared.name,), default_ledger_id=shared.name)
    store.register_strategy_ledgers(s2, (shared.name,), default_ledger_id=shared.name)
    store.register_strategy_ledgers(s3, (other.name,), default_ledger_id=other.name)
    queue = EventQueue()

    queue.push_event(EventDraft(EventKind.LEDGER, pd.Timestamp("2024-01-01"), ledger=shared))
    run(account, queue, registry.resolve(), step_mode=True, step_callback=step_records.append)

    assert seen == [frozenset({s1, s2})]
    assert [item["strategy"] for item in step_records[0]["strategies"]] == ["A", "B"]
    assert [item["ledger"] for item in step_records[0]["ledgers_before"]] == ["shared-book"]
    assert step_records[0]["event_kind"] == "LEDGER"
    assert step_records[0]["current_event"]["event_kind"] == "LEDGER"
    assert step_records[0]["current_event"]["batch_count"] == 1
    assert step_records[0]["current_event"]["subjects"][0]["ledger"] == "shared-book"
    assert "C" not in {item["strategy"] for item in step_records[0]["strategies"]}
    assert "other-book" not in {item["ledger"] for item in step_records[0]["ledgers_before"]}


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

    account = _account([s], active_flow_names=frozenset({"pre_flow", "on_signal", "post_flow"}))
    queue = EventQueue()
    queue.push_event(EventDraft(EventKind.SIGNAL, pd.Timestamp("2024-01-01"), s))

    run(account, queue, registry.resolve(), progress=lambda completed, total, label: seen.append((completed, total, label)))

    labels = [label for _, _, label in seen]
    assert "预处理" in labels       # pre_flow's description
    assert "post_flow" in labels    # post's name (no description given)
    assert "on_signal" in labels


def test_step_mode_emits_every_flow_invocation_and_keeps_phase_coverage():
    """The client receives every real flow invocation without sampling.

    Each record is emitted after compute, so the declared output contains the
    value the flow just produced. Repeating the same event flow produces the
    next step because Enter means exactly one flow invocation.
    """
    from tools.testers.backtest.modules.base import FieldRef

    strategy = Strategy(alias="S")
    output = FieldRef("audit_output", owner="Audit")
    records: list[dict] = []

    def compute(value: str):
        def _compute(account, ctx) -> None:
            ctx.set(output, value)
        return _compute

    pre = Flow(
        "pre", inputs=(), outputs=(output,), phase=Phase.PRE_REPLAY,
        description="准备审计输入", compute=compute("pre"),
    )
    event = Flow(
        "event", inputs=(output,), outputs=(output,), phase=Phase.PER_EVENT,
        event_kind=EventKind.SIGNAL, description="处理审计事件", compute=compute("event"),
    )
    post = Flow(
        "post", inputs=(output,), outputs=(output,), phase=Phase.POST_REPLAY,
        description="整理审计结果", compute=compute("post"),
    )
    registry = FlowRegistry()
    for flow in (pre, event, post):
        registry.register_flow(flow)

    account = _account([strategy], active_flow_names=frozenset({"pre", "event", "post"}))
    queue = EventQueue()
    queue.push_event(EventDraft(EventKind.SIGNAL, pd.Timestamp("2024-01-01"), strategy))
    queue.push_event(EventDraft(EventKind.SIGNAL, pd.Timestamp("2024-01-02"), strategy))

    run(account, queue, registry.resolve(), step_mode=True, step_callback=records.append)

    assert [(record["flow_phase"], record["flow_id"]) for record in records] == [
        ("pre_replay", "pre"),
        ("per_event", "event"),
        ("per_event", "event"),
        ("post_replay", "post"),
    ]
    assert all(record["phase"] == "step" for record in records)
    assert records[0]["outputs"][0]["values"][0]["value"] == "pre"
    assert records[1]["outputs"][0]["values"][0]["value"] == "event"
    assert records[2]["outputs"][0]["values"][0]["value"] == "event"
    assert records[3]["outputs"][0]["values"][0]["value"] == "post"


def test_step_fast_forward_skips_audit_capture_but_not_flow_compute():
    strategy = Strategy(alias="S-fast")
    computed: list[str] = []
    records: list[dict] = []

    class Callback:
        def should_capture(self, timestamp) -> bool:
            return False

        def __call__(self, record: dict) -> None:
            records.append(record)

    flow = Flow(
        "fast", inputs=(), outputs=(), phase=Phase.PRE_REPLAY,
        compute=lambda account, ctx: computed.append("ran"),
    )
    account = _account([strategy], active_flow_names=frozenset({"fast"}))

    run(account, EventQueue(), [flow], step_mode=True, step_callback=Callback())

    assert computed == ["ran"]
    assert records == []


def test_step_mode_reports_mutable_event_payload_before_and_after_per_strategy():
    strategy = Strategy(alias="S-payload")
    records: list[dict] = []

    def mutate_payload(account, ctx) -> None:
        ctx.payloads_for(strategy)[0]["fee_cost"] = 12.5

    flow = Flow(
        "mutate_payload",
        inputs=(),
        outputs=(),
        phase=Phase.PER_EVENT,
        event_kind=EventKind.ORDER,
        description="修改订单载荷",
        compute=mutate_payload,
    )
    account = _account([strategy], active_flow_names=frozenset({"mutate_payload"}))
    queue = EventQueue()
    queue.push_event(EventDraft(
        EventKind.ORDER,
        pd.Timestamp("2024-01-01"),
        strategy,
        {"quantity": 2.0},
    ))

    run(account, queue, [flow], step_mode=True, step_callback=records.append)

    assert records[0]["event_payloads"] == []
    assert records[0]["event_payloads_after"] == []
    assert records[0]["event_payload_changes"] == [{
        "scope": "strategy",
        "strategy": "S-payload",
        "ledger": None,
        "cash_pool": None,
        "before": [{"quantity": 2.0}],
        "after": [{"fee_cost": 12.5, "quantity": 2.0}],
    }]


def test_step_mode_does_not_label_unrelated_ledger_event_as_dmtm():
    strategy = Strategy(alias="S-ledger")
    records: list[dict] = []
    flow = Flow(
        "apply_daily_mark_to_market",
        inputs=(),
        outputs=(),
        phase=Phase.PER_EVENT,
        event_kind=EventKind.LEDGER,
        compute=lambda account, ctx: None,
    )
    account = _account([strategy], active_flow_names=frozenset({"apply_daily_mark_to_market"}))
    queue = EventQueue()
    queue.push_event(EventDraft(
        EventKind.LEDGER,
        pd.Timestamp("2026-01-05 10:00"),
        strategy=strategy,
        payload={"kind": "margin_requirement_change"},
    ))

    run(account, queue, [flow], step_mode=True, step_callback=records.append)

    assert "dmtm" not in records[0]


def test_step_mode_preserves_data_money_storage_units_in_flow_outputs():
    import orjson

    from tools.data.types.data_money import DataMoney
    from tools.testers.backtest.modules.base import FieldRef

    strategy = Strategy(alias="S-money")
    money_output = FieldRef("money_output", owner="Audit")
    major_money_output = FieldRef("major_money_output", owner="Audit")
    records: list[dict] = []

    def emit_money(account, ctx) -> None:
        ctx.set(
            money_output,
            DataMoney.from_major(
                1234.567,
                currency="CNY",
                use_minor_units=True,
            ),
        )
        ctx.set(
            major_money_output,
            DataMoney.from_major(
                12.345,
                currency="CNY",
                use_minor_units=False,
            ),
        )

    flow = Flow(
        "emit_money",
        inputs=(),
        outputs=(money_output, major_money_output),
        phase=Phase.PRE_REPLAY,
        compute=emit_money,
    )
    account = _account([strategy], active_flow_names=frozenset({"emit_money"}))

    run(account, EventQueue(), [flow], step_mode=True, step_callback=records.append)

    value = records[0]["outputs"][0]["values"][0]["value"]
    assert value == {
        "type": "DataMoney",
        "currency": "CNY",
        "use_minor_units": True,
        "scale": 100,
        "amount": 123457,
        "amount_unit": "minor",
        "minor_units": 123457,
        "major_units": 1234.57,
        "display": "DataMoney(1,234,57 CNY)",
    }
    assert orjson.loads(orjson.dumps(records[0]))["outputs"][0]["values"][0]["value"] == value
    major_value = records[0]["outputs"][1]["values"][0]["value"]
    assert major_value == {
        "type": "DataMoney",
        "currency": "CNY",
        "use_minor_units": False,
        "scale": 100,
        "amount": 12.345,
        "amount_unit": "major",
        "minor_units": None,
        "major_units": 12.345,
        "display": "DataMoney(12.35 CNY)",
    }


def test_step_mode_summarizes_daily_mark_to_market_checkpoint():
    """A DMTM pause exposes the accounting evidence without inspecting internals."""
    from tools.testers.backtest.engines.native.ledger import ledger_identity
    from tools.testers.backtest.modules.base import FieldRef
    from tools.testers.backtest.modules.strategy_book import strategy_book_store_for

    strategy = Strategy(alias="A1")
    ledger = ledger_identity("private:A1")
    snapshot = FieldRef("current_market_snapshot", owner="MarketDataModule")
    accounting = FieldRef("accounting_mode", owner="TradingRuleModule")
    records: list[dict] = []

    flow = Flow(
        "apply_daily_mark_to_market",
        inputs=(snapshot, accounting),
        outputs=(),
        phase=Phase.PER_EVENT,
        event_kind=EventKind.LEDGER,
        compute=lambda account, ctx: None,
    )
    account = _account(
        [strategy],
        active_flow_names=frozenset({"apply_daily_mark_to_market"}),
    )
    strategy_book_store_for(account).register_strategy_ledgers(
        strategy, (ledger.name,), default_ledger_id=ledger.name,
    )
    account.strategy_configs[strategy].field_values[accounting] = "Auto"
    queue = EventQueue()
    queue.push_event(EventDraft(
        EventKind.LEDGER,
        pd.Timestamp("2026-01-05 15:00:00.000000001"),
        payload={
            "kind": "daily_mark_to_market",
            "trading_day": "2026-01-05",
            "ledger_id": ledger.name,
        },
        ledger=ledger,
    ))

    run(account, queue, [flow], step_mode=True, step_callback=records.append)

    assert records[0]["dmtm"] == {
        "events": [{
            "ledger": ledger.name,
            "trading_day": "2026-01-05",
        }],
        "resolved": [],
        "accounting_inputs": [{
            "field": "TradingRuleModule.accounting_mode",
            "values": [{
                "scope": "strategy_config",
                "strategy": "A1",
                "value": "Auto",
            }],
        }],
        "market_rule_inputs": [{
            "field": "MarketDataModule.current_market_snapshot",
            "values": [],
        }],
        "cash_changes": [],
        "position_changes": [],
        "margin_changes": [],
    }


def test_step_mode_dmtm_summary_contains_real_cash_and_position_changes():
    from collections import deque

    import numpy as np
    import orjson

    from tools.data.types.data_money import DataMoney
    from tools.testers.backtest.engines.native.config import LedgerConfig
    from tools.testers.backtest.engines.native.ledger import ledger_identity
    from tools.testers.backtest.engines.native.position import Lot, ProductPosition
    from tools.testers.backtest.modules.cash_pool import set_cash_for_ledger_pool
    from tools.testers.backtest.modules.ledger_module import LedgerModule
    from tools.testers.backtest.modules.market_data import MarketDataModule
    from tools.testers.backtest.modules.strategy_book import strategy_book_store_for
    from tools.testers.backtest.modules.trading_rule import (
        TradingRuleModule,
        _apply_daily_mark_to_market,
    )

    strategy = Strategy(alias="A1")
    product = "DCE|F|LH|2603"
    ledger_key = ledger_identity("private:A1")
    records: list[dict] = []
    account = _account(
        [strategy],
        active_flow_names=frozenset({"prepare_dmtm", "apply_daily_mark_to_market"}),
    )
    strategy_book_store_for(account).register_strategy_ledgers(
        strategy, (ledger_key.name,), default_ledger_id=ledger_key.name,
    )
    ledger = account.ledger_for_strategy(strategy)
    ledger.set(LedgerModule.positions, {
        product: ProductPosition(
            quantity=2,
            lots=deque([Lot(quantity=2, entry_price=100.0, multiplier=1.0, is_today=False)]),
        ),
    })
    account.ledger_configs[ledger.ledger] = LedgerConfig(
        accounting_mode="Auto",
        fee_mode="auto",
        margin_mode="auto",
    )
    set_cash_for_ledger_pool(
        account,
        ledger,
        DataMoney.from_major(1_000.0, currency="CNY", use_minor_units=True),
    )

    def prepare(_account, ctx) -> None:
        ctx.set(MarketDataModule.current_market_snapshot, {
            "settlement": {product: np.float64(110.0)},
            "close": {product: 109.0},
        })
        ctx.set(MarketDataModule.current_historical_fields, {
            product: {
                "CostBasisMethod": "DailyMarkToMarket",
                "SettlementPrice": 110.0,
                "PreSettlementPrice": 100.0,
                "VolumeMultiple": 1.0,
            },
        })

    prepare_flow = Flow(
        "prepare_dmtm",
        inputs=(),
        outputs=(
            MarketDataModule.current_market_snapshot,
            MarketDataModule.current_historical_fields,
        ),
        phase=Phase.PER_EVENT,
        event_kind=EventKind.LEDGER,
        order=1,
        compute=prepare,
    )
    apply_flow = Flow(
        "apply_daily_mark_to_market",
        inputs=TradingRuleModule.apply_daily_mark_to_market.inputs,
        outputs=TradingRuleModule.apply_daily_mark_to_market.outputs,
        phase=Phase.PER_EVENT,
        event_kind=EventKind.LEDGER,
        order=50,
        compute=_apply_daily_mark_to_market,
    )
    queue = EventQueue()
    queue.push_event(EventDraft(
        EventKind.LEDGER,
        pd.Timestamp("2026-01-05 15:00:00.000000001"),
        payload={
            "kind": "daily_mark_to_market",
            "trading_day": "2026-01-05",
            "ledger_id": ledger.ledger_id,
        },
        ledger=ledger.ledger,
    ))

    run(
        account,
        queue,
        [prepare_flow, apply_flow],
        step_mode=True,
        step_callback=records.append,
    )

    dmtm = records[1]["dmtm"]
    assert dmtm["events"] == [{
        "ledger": ledger.ledger_id,
        "trading_day": "2026-01-05",
    }]
    assert dmtm["cash_changes"]
    cash_change = dmtm["cash_changes"][0]
    assert cash_change["before"]["type"] == "DataMoney"
    assert cash_change["before"]["use_minor_units"] is True
    assert cash_change["before"]["minor_units"] == 100_000
    assert cash_change["after"]["type"] == "DataMoney"
    assert cash_change["after"]["use_minor_units"] is True
    assert cash_change["after"]["minor_units"] == 102_000
    assert dmtm["position_changes"]
    position_change = dmtm["position_changes"][0]
    assert position_change["before_count"] == 1
    assert position_change["after_count"] == 1
    assert position_change["changes"][0]["instrument"] == product
    assert "before" not in position_change
    assert "after" not in position_change
    assert records[1]["ledger_changes"] == []
    positions_output = next(
        item for item in records[1]["outputs"]
        if item["field"] == "LedgerModule.positions"
    )
    assert positions_output == {
        "field": "LedgerModule.positions",
        "values": [],
        "represented_by": "output_changes",
    }
    assert dmtm["market_rule_inputs"]
    resolved = next(
        item for item in records[1]["outputs"]
        if item["field"] == "TradingRuleModule.resolved_daily_mark_to_market"
    )
    assert resolved["values"] == [{
        "scope": "context",
        "value": {
            ledger.ledger_id: {
                product: {
                    "enabled": True,
                    "source": "historical.CostBasisMethod",
                    "cost_basis_method": "FIFO",
                },
            },
        },
    }]
    assert dmtm["resolved"] == resolved["values"]
    assert orjson.loads(orjson.dumps(records[1]))["dmtm"]["market_rule_inputs"]
