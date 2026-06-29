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
from typing import TYPE_CHECKING, Any, Callable

import pandas as pd

from .events import EventDraft, EventKind
from .flow import Flow, FlowOverride, Phase

if TYPE_CHECKING:
    from .ledger import AccountState
    from .strategy import Strategy
    from tools.testers.backtest.modules.base import FieldRef


class SchedulerError(Exception):
    pass


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

    @property
    def effective_description(self) -> str:
        return self.description or self.name


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
                compute = _wrap(ov.compute, compute)
            resolved.append(ResolvedFlow(
                name=name, inputs=tuple(inputs), outputs=base.outputs,
                phase=base.phase, event_kind=base.event_kind, order=base.order,
                after=base.after, before=base.before, compute=compute,
                description=base.description,
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

    def pending_count(self) -> int:
        """O(1) -- `len()` on a list, not a heap walk."""
        return len(self._heap)

    def run_until_drained(self) -> None:
        """Progress reporting lives in `make_dispatcher` (Flow-level), not
        here -- a batch can fan out across many strategies x Flows, and
        that inner loop is where real work (and real wall-clock time) is
        spent, not the batching loop itself."""
        while self._heap:
            _, _, _, first = heapq.heappop(self._heap)
            batch = [first]
            while (
                self._heap
                and self._heap[0][0] == first.timestamp
                and self._heap[0][1] == first.kind
            ):
                batch.append(heapq.heappop(self._heap)[3])
            dispatcher = self._dispatchers.get(first.kind)
            if dispatcher is not None:
                dispatcher(batch)


# ── main loop ─────────────────────────────────────────────────────


class _ProgressTracker:
    """Shared across every phase/dispatcher in one `run()` call so progress
    accumulates correctly instead of resetting per phase or per event kind.
    Unit = one Flow.compute() call, not one event or one strategy -- a
    single call already covers every applicable strategy internally, and
    that's the actual unit of work the scheduler can see without forcing
    every Flow body to report progress mid-loop (which would couple
    business logic to progress-reporting infrastructure, see plan)."""

    def __init__(
        self,
        callback: Callable[[int, int, str], None] | None,
        pre_replay_count: int,
        post_replay_count: int,
        event_queue: EventQueue,
    ) -> None:
        self._callback = callback
        self._pre_replay_remaining = pre_replay_count
        self._post_replay_remaining = post_replay_count
        self._event_queue = event_queue
        self._completed = 0

    def tick(self, label: str, *, phase: Phase) -> None:
        if self._callback is None:
            return
        if phase is Phase.PRE_REPLAY:
            self._pre_replay_remaining -= 1
        elif phase is Phase.POST_REPLAY:
            self._post_replay_remaining -= 1
        self._completed += 1
        # Each pending event will trigger at least one Flow call once
        # popped -- a lower-bound, live-updating estimate, not a fixed
        # upfront count (the PER_EVENT queue can still grow).
        total = (
            self._completed + self._pre_replay_remaining
            + self._post_replay_remaining + self._event_queue.pending_count()
        )
        from tools.testers.backtest.engines.workers.runners.common import should_report_progress
        if should_report_progress(self._completed, total):
            self._callback(self._completed, total, label)


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
            f.compute(account, ctx)
            if tracker is not None:
                tracker.tick(f.effective_description, phase=f.phase)
    return handler


def run(
    account: "AccountState",
    event_queue: EventQueue,
    resolved_flows: list[ResolvedFlow],
    progress: Callable[[int, int, str], None] | None = None,
) -> None:
    """Invariant: run() itself never calls event_queue.push_event directly
    — events are only ever registered by some Flow's compute via
    ctx.set()/ctx.set_for() (FlowContext._push_if_event). Any future change
    that wants to conveniently push an event from inside this function
    means the design has drifted — go fix a Flow, not this function.

    `progress(completed, total, label)`, if given, fires once per
    Flow.compute() call across ALL three phases (not just PER_EVENT) --
    `label` is that Flow's qualified_name, `total` is a live, growing-as-
    needed estimate (see _ProgressTracker), not a fixed upfront count."""
    groups = sort_and_validate(resolved_flows)
    pre_replay_flows = groups.get((Phase.PRE_REPLAY, None), ())
    post_replay_flows = groups.get((Phase.POST_REPLAY, None), ())
    tracker = _ProgressTracker(progress, len(pre_replay_flows), len(post_replay_flows), event_queue)

    for (phase, event_kind), ordered_flows in groups.items():
        if phase is Phase.PER_EVENT:
            event_queue.set_dispatcher(
                event_kind, make_dispatcher(ordered_flows, account, event_queue, tracker))

    ctx = FlowContext(timestamp=None, event_queue=event_queue)
    for f in pre_replay_flows:
        f.compute(account, ctx)
        tracker.tick(f.effective_description, phase=Phase.PRE_REPLAY)

    event_queue.run_until_drained()

    ctx = FlowContext(timestamp=None, event_queue=event_queue)
    for f in post_replay_flows:
        f.compute(account, ctx)
        tracker.tick(f.effective_description, phase=Phase.POST_REPLAY)
