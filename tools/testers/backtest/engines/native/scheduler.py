"""The scheduler — FlowRegistry (collects Flow/FlowOverride into decorator
chains), sort_and_validate (per-(phase, event_kind) ordering + dependency
checks), FlowContext (per-dispatch-batch scratch), EventQueue (priority
queue, batches same (timestamp, kind)), and run() (wires it all together).

The scheduler never hardcodes business logic — it only knows Phase/Flow/
EventKind/FieldRef shapes, not what any specific module computes.
"""

from __future__ import annotations

import heapq
import itertools
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Protocol, cast

import pandas as pd

from .events import EventDraft, EventKind
from .flow import Flow, FlowOverride, Phase

if TYPE_CHECKING:
    from .ledger import AccountState
    from .strategy import Strategy
    from tools.testers.backtest.modules.base import FieldRef


class SchedulerError(Exception):
    pass


class ProgressSink(Protocol):
    def emit_activity_manifest(self, phases: list[dict[str, Any]]) -> None: ...
    def emit_activity(self, **payload: Any) -> None: ...
    def emit_signal_progress(
        self,
        *,
        completed: int,
        total: int,
        phase: str = "event_replay",
        percent: float | None = None,
    ) -> None: ...


_PHASE_LABELS: dict[str, str] = {
    "pre_replay": "回放准备",
    "event_replay": "事件回放",
    "post_replay": "结果整理",
}


_FLOW_LABELS: dict[str, str] = {
    "check_market_data_coverage": "检查产品覆盖期",
    "resolve_product_selection": "解析产品路径",
    "expand_term_structure": "展开期限结构",
    "resolve_tradable_target_weights": "解析可交易合约目标",
    "register_force_close_notices": "登记交割强平通知",
    "register_rollover_notices": "登记换月通知",
    "load_raw_market_data": "装载行情数据",
    "build_trading_day_resolver": "建立交易日映射",
    "load_historical_fields": "加载历史交易规则字段",
    "causal_valuation": "生成因果估值序列",
    "initialize_ledgers": "初始化交易账本",
    "schedule_bar_events": "登记行情事件",
    "signal_live": "处理实时因子信号",
    "signal_precomputed": "登记预计算信号",
    "lookup_current_prices_on_signal": "读取信号时点价格",
    "lookup_current_prices_on_bar": "读取行情时点价格",
    "lookup_current_prices_on_order": "读取订单时点价格",
    "handle_rollover_notice": "处理换月通知",
    "handle_delivery_force_close_notice": "处理交割强平通知",
    "lookup_volume_on_signal": "读取成交量",
    "lookup_historical_fields_on_signal": "读取交易规则字段",
    "lookup_historical_fields_on_order": "读取订单交易规则字段",
    "group_quantile_membership": "计算分组隶属",
    "equity_on_signal": "计算信号时点权益",
    "size_order": "计算目标下单量",
    "construct_orders": "构造订单",
    "constrain_to_ledger_cash": "按现金约束调整订单",
    "schedule_order_execution": "登记订单执行事件",
    "cash_update": "更新现金与持仓",
    "equity_on_order": "计算订单后权益",
    "record_equity_on_signal": "记录信号时点净值",
    "record_equity_on_order": "记录订单后净值",
    "finalize_order": "确认订单终态",
    "flush_equity_post_replay": "整理净值曲线",
    "compute_risk_metrics": "计算风险指标",
}


# ── FlowRegistry ──────────────────────────────────────────────────


@dataclass(frozen=True)
class ResolvedFlow:
    name: str
    inputs: tuple["FieldRef", ...]
    outputs: tuple["FieldRef", ...]
    phase: Phase
    event_kind: EventKind | None
    order: int
    after: tuple[Flow, ...]
    before: tuple[Flow, ...]
    compute: Callable[..., None]
    description: str = ""
    strategy_scoped: bool = False

    @property
    def effective_description(self) -> str:
        return self.description or _FLOW_LABELS.get(self.name, self.name)

    @property
    def activity_key(self) -> str:
        event = self.event_kind.name.lower() if self.event_kind is not None else "once"
        return f"{self.phase.value}.{event}.{self.name}"


def _wrap(override_compute: Callable, base_compute: Callable) -> Callable:
    def wrapped(account, ctx) -> None:
        override_compute(account, ctx, base_compute)
    return wrapped


class FlowRegistry:
    """Keyed by (name, phase, event_kind), not name alone -- a logical
    Flow "name" can legitimately be registered twice under the SAME name
    if the two registrations live in different (phase, event_kind) groups
    (e.g. FactorSignalModule's "signal_precomputed": one PRE_REPLAY Flow
    that schedules timestamps, one PER_EVENT Flow that looks up the value,
    both gated by the same StrategyConfig.active_flow_names entry by
    design). Duplicate (name, phase, event_kind) is still rejected --
    that's a real conflict, not an intentional phase-split."""

    def __init__(self) -> None:
        self._flows: dict[tuple[str, Phase, EventKind | None], Flow] = {}
        self._overrides: dict[str, list[FlowOverride]] = defaultdict(list)

    def register_flow(self, flow: Flow) -> None:
        key = (flow.name, flow.phase, flow.event_kind)
        if key in self._flows:
            raise ValueError(f"duplicate flow registration: {key}")
        self._flows[key] = flow

    def register_override(self, override: FlowOverride) -> None:
        for name in override.flow_names:
            self._overrides[name].append(override)

    def overrides_for(self, flow_name: str) -> list[FlowOverride]:
        return list(self._overrides.get(flow_name, ()))

    def resolve(self) -> list[ResolvedFlow]:
        resolved: list[ResolvedFlow] = []
        for (name, _phase, _event_kind), base in self._flows.items():
            compute = base.compute
            inputs = set(base.inputs)
            for ov in self._overrides.get(name, ()):
                inputs |= set(ov.extra_inputs)
                if ov.compute is not None:
                    compute = _wrap(ov.compute, compute)
            resolved.append(ResolvedFlow(
                name=name, inputs=tuple(inputs), outputs=base.outputs,
                phase=base.phase, event_kind=base.event_kind, order=base.order,
                after=base.after, before=base.before, compute=compute,
                description=base.description, strategy_scoped=base.strategy_scoped,
            ))
        return resolved


# ── sort_and_validate ─────────────────────────────────────────────


def _group_key(f: ResolvedFlow) -> tuple[Phase, EventKind | None]:
    return (f.phase, f.event_kind)


def sort_and_validate(
    flows: list[ResolvedFlow],
) -> dict[tuple[Phase, EventKind | None], list[ResolvedFlow]]:
    groups: dict[tuple[Phase, EventKind | None], list[ResolvedFlow]] = defaultdict(list)
    for f in flows:
        if f.phase is Phase.PER_EVENT and f.event_kind is None:
            raise SchedulerError(f"flow {f.name!r} phase=PER_EVENT must declare event_kind")
        if f.phase is not Phase.PER_EVENT and f.event_kind is not None:
            raise SchedulerError(f"flow {f.name!r} phase={f.phase} must not declare event_kind")
        groups[_group_key(f)].append(f)

    result: dict[tuple[Phase, EventKind | None], list[ResolvedFlow]] = {}
    for key, group in groups.items():
        result[key] = _sort_and_validate_group(group)
    return result


def _sort_and_validate_group(flows: list[ResolvedFlow]) -> list[ResolvedFlow]:
    ordered = sorted(flows, key=lambda f: (f.order, f.name))
    position = {f.name: i for i, f in enumerate(ordered)}
    producer_of: dict["FieldRef", str] = {}
    for f in ordered:
        for out in f.outputs:
            producer_of[out] = f.name

    for f in ordered:
        for inp in f.inputs:
            owner = producer_of.get(inp)
            if owner is not None and position[owner] > position[f.name]:
                raise SchedulerError(
                    f"flow {f.name!r} depends on {inp.qualified_name!r}, "
                    f"but producer flow {owner!r} is ordered after it")
        for dep in f.after:
            if dep.name in position and position[dep.name] > position[f.name]:
                raise SchedulerError(f"flow {f.name!r} must be ordered after {dep.qualified_name!r}")
        for dep in f.before:
            if dep.name in position and position[dep.name] < position[f.name]:
                raise SchedulerError(f"flow {f.name!r} must be ordered before {dep.qualified_name!r}")
    return ordered


# ── FlowContext ───────────────────────────────────────────────────


class FlowContext:
    """Per-dispatch-batch scratch. `get`/`set` are unkeyed (PRE_REPLAY/
    POST_REPLAY, no "active strategies" concept); `get_for`/`set_for` are
    keyed by (FieldRef, Strategy) for PER_EVENT batches with multiple
    active strategies. Setting an EventDraft (or list of them) pushes it
    into the event queue immediately — no buffering, no separate flush."""

    def __init__(
        self,
        timestamp: pd.Timestamp | None,
        event_queue: "EventQueue",
        active_strategies: frozenset["Strategy"] = frozenset(),
        drafts_by_strategy: dict["Strategy", list[EventDraft]] | None = None,
    ) -> None:
        self.timestamp = timestamp
        self.active_strategies = active_strategies
        # A strategy can have multiple simultaneous drafts in one dispatch
        # batch (e.g. several ORDER events for different products firing at
        # the same timestamp) -- always a list, never collapsed to one.
        self._drafts_by_strategy: dict["Strategy", list[EventDraft]] = drafts_by_strategy or {}
        self._event_queue = event_queue
        self._values: dict["FieldRef", Any] = {}
        self._values_by_strategy: dict["FieldRef", dict["Strategy", Any]] = {}

    def get(self, ref: "FieldRef", default: Any = None) -> Any:
        return self._values.get(ref, default)

    def set(self, ref: "FieldRef", value: Any) -> None:
        self._values[ref] = value
        self._push_if_event(value)

    def get_for(self, ref: "FieldRef", strategy: "Strategy", default: Any = None) -> Any:
        return self._values_by_strategy.get(ref, {}).get(strategy, default)

    def set_for(self, ref: "FieldRef", strategy: "Strategy", value: Any) -> None:
        self._values_by_strategy.setdefault(ref, {})[strategy] = value
        self._push_if_event(value)

    def _push_if_event(self, value: Any) -> None:
        if isinstance(value, EventDraft):
            self._event_queue.push_event(value)
        elif isinstance(value, list) and value and isinstance(value[0], EventDraft):
            push_events = getattr(self._event_queue, "push_events", None)
            if callable(push_events):
                push_events(value)
            else:
                for draft in value:
                    self._event_queue.push_event(draft)

    def payload_for(self, strategy: "Strategy") -> Any:
        """For event kinds that only ever carry one draft per strategy per
        batch (SIGNAL). Raises if this strategy actually has more than one
        draft in this batch -- that's an ORDER-kind situation and the
        caller should use `payloads_for` instead, not silently pick one."""
        drafts = self._drafts_by_strategy[strategy]
        if len(drafts) != 1:
            raise SchedulerError(
                f"payload_for expected exactly one draft for {strategy!r} in this "
                f"batch, found {len(drafts)} -- use payloads_for for event kinds "
                "that can carry multiple simultaneous drafts per strategy (e.g. ORDER)")
        return drafts[0].payload

    def payloads_for(self, strategy: "Strategy") -> list[Any]:
        """All payloads for this strategy in this dispatch batch, in the
        order they were popped off the EventQueue (stable for equal
        timestamp+kind, see EventQueue's counter tiebreak). A strategy can
        have several simultaneous ORDER events at one timestamp (one per
        product being rebalanced) -- all of them must be processed, not
        just the last one."""
        return [draft.payload for draft in self._drafts_by_strategy.get(strategy, ())]

    def draft_for(self, strategy: "Strategy") -> EventDraft:
        drafts = self._drafts_by_strategy[strategy]
        if len(drafts) != 1:
            raise SchedulerError(
                f"draft_for expected exactly one draft for {strategy!r} in this "
                f"batch, found {len(drafts)}")
        return drafts[0]


# ── EventQueue ────────────────────────────────────────────────────


class EventQueue:
    """Single global priority queue keyed (timestamp, kind, counter).
    `kind` (an IntEnum) participates directly in sort ordering — no-
    lookahead is guaranteed structurally by causal_valuation's precomputed
    ffill-only series, not by queue mechanics, so there's no separate
    "bucket"/"tick" concept here."""

    def __init__(self) -> None:
        self._heap: list[tuple[pd.Timestamp, EventKind, int, EventDraft]] = []
        self._counter = itertools.count()
        self._dispatchers: dict[EventKind, Callable[[list[EventDraft]], None]] = {}

    def set_dispatcher(self, kind: EventKind, dispatcher: Callable[[list[EventDraft]], None]) -> None:
        self._dispatchers[kind] = dispatcher

    def push_event(self, draft: EventDraft) -> None:
        heapq.heappush(self._heap, (draft.timestamp, draft.kind, next(self._counter), draft))

    def push_events(self, drafts: list[EventDraft]) -> None:
        if not drafts:
            return
        self._heap.extend((draft.timestamp, draft.kind, next(self._counter), draft) for draft in drafts)
        heapq.heapify(self._heap)

    def pending_count(self) -> int:
        """O(1) -- `len()` on a list, not a heap walk."""
        return len(self._heap)

    def pending_count_by_kind(self, kind: EventKind) -> int:
        return sum(1 for _, draft_kind, _, _ in self._heap if draft_kind is kind)

    def run_until_drained(self) -> None:
        """Progress reporting lives in `make_dispatcher` (Flow-level), not
        here -- a batch can fan out across many strategies x Flows, and
        that inner loop is where real work (and real wall-clock time) is
        spent, not the batching loop itself."""
        while self._heap:
            first_ts, first_kind, _, first = heapq.heappop(self._heap)
            batch = [first]
            while (
                self._heap
                and self._heap[0][0] == first_ts
                and self._heap[0][1] == first_kind
            ):
                batch.append(heapq.heappop(self._heap)[3])
            dispatcher = self._dispatchers.get(first.kind)
            if dispatcher is not None:
                dispatcher(batch)


class _ProgressTracker:
    """Backtest activity reporter.

    The UI progress bar is keyed to initial SIGNAL event completion. Flow
    activity is a parallel stream used for text rotation and process display;
    it deliberately does not expose completed/total flow counts.
    """

    def __init__(
        self,
        callback: Callable[[int, int, str], None] | None,
        activity_sink: ProgressSink | None,
        event_queue: EventQueue,
    ) -> None:
        self._callback = callback
        self._activity_sink = activity_sink
        self._event_queue = event_queue
        self._completed = 0
        self._signal_total = 0
        self._signal_completed = 0
        self._pre_total = 0
        self._pre_completed = 0
        self._post_total = 0
        self._post_completed = 0

    def emit_manifest(self, groups: dict[tuple[Phase, EventKind | None], list[ResolvedFlow]]) -> None:
        if self._activity_sink is not None:
            self._activity_sink.emit_activity_manifest(activity_manifest_from_groups(groups))

    def set_phase_totals(self, *, pre_total: int, post_total: int) -> None:
        self._pre_total = max(0, pre_total)
        self._post_total = max(0, post_total)

    def note_signal_queue_ready(self) -> None:
        self._signal_total = self._event_queue.pending_count_by_kind(EventKind.SIGNAL)
        self._signal_completed = 0
        if self._activity_sink is not None:
            self._activity_sink.emit_signal_progress(
                completed=0,
                total=self._signal_total,
                phase="event_replay",
                percent=10.0,
            )

    def activity(self, flow: ResolvedFlow, *, timestamp: pd.Timestamp | None, phase: str | None = None) -> None:
        if self._activity_sink is None:
            return
        activity_phase = phase or _activity_phase_for_flow(flow)
        ts_text = timestamp.isoformat() if timestamp is not None else ""
        self._activity_sink.emit_activity(
            phase=activity_phase,
            phase_label=_PHASE_LABELS.get(activity_phase, activity_phase),
            flow_key=flow.activity_key,
            flow_name=flow.name,
            flow_label=flow.effective_description,
            display_order=flow.order,
            event_kind=flow.event_kind.name if flow.event_kind is not None else "",
            timestamp=ts_text,
            timezone=str(getattr(getattr(timestamp, "tzinfo", None), "zone", "") or ""),
            message=_activity_message(ts_text, flow.effective_description),
        )

    def tick(self, label: str, *, phase: Phase) -> None:
        self._completed += 1
        if self._callback is not None:
            self._callback(self._completed, max(self._completed, 1), label)

    def signal_batch_done(self, batch_size: int) -> None:
        if batch_size <= 0:
            return
        self._signal_completed = min(self._signal_total, self._signal_completed + batch_size)
        if self._activity_sink is not None:
            ratio = 1.0 if self._signal_total <= 0 else self._signal_completed / self._signal_total
            self._activity_sink.emit_signal_progress(
                completed=self._signal_completed,
                total=self._signal_total,
                phase="event_replay",
                percent=10.0 + ratio * 80.0,
            )

    def phase_flow_done(self, *, phase: str) -> None:
        if self._activity_sink is None:
            return
        if phase == "pre_replay":
            self._pre_completed = min(self._pre_total, self._pre_completed + 1)
            ratio = 1.0 if self._pre_total <= 0 else self._pre_completed / self._pre_total
            self._activity_sink.emit_signal_progress(
                completed=self._pre_completed,
                total=self._pre_total,
                phase=phase,
                percent=ratio * 10.0,
            )
        elif phase == "post_replay":
            self._post_completed = min(self._post_total, self._post_completed + 1)
            ratio = 1.0 if self._post_total <= 0 else self._post_completed / self._post_total
            self._activity_sink.emit_signal_progress(
                completed=self._post_completed,
                total=self._post_total,
                phase=phase,
                percent=90.0 + ratio * 10.0,
            )

    def event_replay_done(self) -> None:
        if self._activity_sink is not None:
            self._activity_sink.emit_signal_progress(
                completed=self._signal_total,
                total=self._signal_total,
                phase="event_replay",
                percent=90.0,
            )

    def complete(self) -> None:
        if self._activity_sink is not None:
            self._activity_sink.emit_signal_progress(completed=1, total=1, phase="done", percent=100.0)


def make_dispatcher(
    ordered_flows: list[ResolvedFlow],
    account: "AccountState",
    event_queue: EventQueue,
    tracker: "_ProgressTracker | None" = None,
) -> Callable[[list[EventDraft]], None]:
    def handler(batch: list[EventDraft]) -> None:
        timestamp = batch[0].timestamp
        # A strategy can appear more than once in one batch (e.g. several
        # ORDER events for different products at the same timestamp) --
        # group by strategy without dropping any draft. One pass, O(batch).
        drafts_by_strategy: dict["Strategy", list[EventDraft]] = {}
        for draft in batch:
            drafts_by_strategy.setdefault(draft.strategy, []).append(draft)
        all_active = frozenset(drafts_by_strategy)
        # ONE ctx for the whole batch -- this is what lets one Flow's
        # ctx.set_for(...) be read by a later Flow in the same batch (e.g.
        # LedgerModule.equity_on_signal -> OrderBookModule.size_order).
        # active_strategies is narrowed per Flow call (different Flows can
        # apply to different subsets), but _values/_values_by_strategy
        # persist across the whole batch.
        ctx = FlowContext(
            timestamp=timestamp, event_queue=event_queue,
            active_strategies=all_active, drafts_by_strategy=drafts_by_strategy,
        )
        for f in ordered_flows:
            applicable = frozenset(
                s for s in all_active
                if f.name in account.config_for(s).active_flow_names
            )
            if not applicable:
                continue
            ctx.active_strategies = applicable
            if tracker is not None:
                tracker.activity(f, timestamp=timestamp, phase="event_replay")
            f.compute(account, ctx)
            if tracker is not None:
                tracker.tick(f.effective_description, phase=f.phase)
        if tracker is not None and batch and batch[0].kind is EventKind.SIGNAL:
            tracker.signal_batch_done(len(batch))
    return handler


def _strategies_using_flow(account: "AccountState", flow_name: str) -> frozenset["Strategy"]:
    return frozenset(
        strategy for strategy in account.strategy_configs
        if flow_name in account.config_for(strategy).active_flow_names
    )


def _pre_post_applicable_strategies(account: "AccountState", flow: ResolvedFlow) -> frozenset["Strategy"]:
    if not flow.strategy_scoped:
        return frozenset(account.strategy_configs)
    return _strategies_using_flow(account, flow.name)


def run(
    account: "AccountState",
    event_queue: EventQueue,
    resolved_flows: list[ResolvedFlow],
    progress: Callable[[int, int, str], None] | None = None,
    activity_sink: ProgressSink | None = None,
) -> None:
    """Invariant: run() itself never calls event_queue.push_event directly
    — events are only ever registered by some Flow's compute via
    ctx.set()/ctx.set_for() (FlowContext._push_if_event). Any future change
    that wants to conveniently push an event from inside this function
    means the design has drifted — go fix a Flow, not this function.

    `progress(completed, total, label)` is kept for legacy coarse callers.
    `activity_sink` is the native UI contract: manifest + activity +
    signal-progress, with no flow-count totals exposed to the user."""
    groups = sort_and_validate(resolved_flows)
    pre_replay_flows = groups.get((Phase.PRE_REPLAY, None), ())
    post_replay_flows = groups.get((Phase.POST_REPLAY, None), ())
    tracker = _ProgressTracker(progress, activity_sink, event_queue)
    tracker.emit_manifest(groups)
    applicable_pre_flows = [
        f for f in pre_replay_flows
        if _pre_post_applicable_strategies(account, f)
    ]
    applicable_post_flows = [
        f for f in post_replay_flows
        if _pre_post_applicable_strategies(account, f)
    ]
    tracker.set_phase_totals(pre_total=len(applicable_pre_flows), post_total=len(applicable_post_flows))

    for (phase, event_kind), ordered_flows in groups.items():
        if phase is Phase.PER_EVENT:
            event_queue.set_dispatcher(
                cast(EventKind, event_kind), make_dispatcher(ordered_flows, account, event_queue, tracker))

    ctx = FlowContext(timestamp=None, event_queue=event_queue)
    for f in pre_replay_flows:
        applicable = _pre_post_applicable_strategies(account, f)
        if not applicable:
            continue
        ctx.active_strategies = applicable
        tracker.activity(f, timestamp=None, phase="pre_replay")
        f.compute(account, ctx)
        tracker.phase_flow_done(phase="pre_replay")
        tracker.tick(f.effective_description, phase=Phase.PRE_REPLAY)

    tracker.note_signal_queue_ready()
    event_queue.run_until_drained()
    tracker.event_replay_done()

    ctx = FlowContext(timestamp=None, event_queue=event_queue)
    for f in post_replay_flows:
        applicable = _pre_post_applicable_strategies(account, f)
        if not applicable:
            continue
        ctx.active_strategies = applicable
        tracker.activity(f, timestamp=None, phase="post_replay")
        f.compute(account, ctx)
        tracker.phase_flow_done(phase="post_replay")
        tracker.tick(f.effective_description, phase=Phase.POST_REPLAY)
    tracker.complete()


def _activity_phase(phase: Phase) -> str:
    if phase is Phase.PER_EVENT:
        return "event_replay"
    return phase.value


def _activity_phase_for_flow(flow: ResolvedFlow) -> str:
    return _activity_phase(flow.phase)


def _activity_message(timestamp: str, label: str) -> str:
    if timestamp:
        return f"{timestamp} 正在{label}"
    return f"正在{label}"


def activity_manifest_from_groups(
    groups: dict[tuple[Phase, EventKind | None], list[ResolvedFlow]],
) -> list[dict[str, Any]]:
    phase_specs: list[dict[str, Any]] = []
    pre_all = list(groups.get((Phase.PRE_REPLAY, None), ()))
    phase_specs.append(_phase_spec("pre_replay", pre_all))

    event_flows: list[ResolvedFlow] = []
    for (phase, _kind), flows in groups.items():
        if phase is Phase.PER_EVENT:
            event_flows.extend(flows)
    event_flows = sorted(event_flows, key=lambda f: (f.order, f.event_kind or EventKind.SIGNAL, f.name))
    phase_specs.append(_phase_spec("event_replay", event_flows))

    post = groups.get((Phase.POST_REPLAY, None), ())
    phase_specs.append(_phase_spec("post_replay", post))
    return phase_specs


def _phase_spec(key: str, flows: list[ResolvedFlow] | tuple[ResolvedFlow, ...]) -> dict[str, Any]:
    return {
        "key": key,
        "label": _PHASE_LABELS.get(key, key),
        "flows": [
            {
                "phase": key,
                "flow_key": flow.activity_key,
                "flow_name": flow.name,
                "flow_label": flow.effective_description,
                "display_order": idx,
                "event_kind": flow.event_kind.name if flow.event_kind is not None else "",
            }
            for idx, flow in enumerate(flows, start=1)
        ],
    }
