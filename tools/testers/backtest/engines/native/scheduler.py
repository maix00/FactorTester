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
import warnings
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Protocol, cast

import pandas as pd

from .events import EventDraft, EventKind
from .flow import Flow, FlowOverride, Phase

if TYPE_CHECKING:
    from .ledger import BacktestRunState
    from .ledger import Ledger
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


# ── FlowRegistry ──────────────────────────────────────────────────


@dataclass(frozen=True)
class ResolvedFlow:
    name: str
    owner: str
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
        return self.description or self.name

    @property
    def activity_key(self) -> str:
        event = self.event_kind.name.lower() if self.event_kind is not None else "once"
        return f"{self.phase.value}.{event}.{self.name}"


def _flow_qualified_name(flow: ResolvedFlow) -> str:
    return f"{flow.owner}.{flow.name}" if getattr(flow, "owner", "") else f".{flow.name}"


def _wrap(override_compute: Callable, base_compute: Callable) -> Callable:
    def wrapped(state, ctx) -> None:
        override_compute(state, ctx, base_compute)
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
                name=name, owner=base.owner, inputs=tuple(inputs), outputs=base.outputs,
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
        active_ledgers: frozenset["Ledger"] = frozenset(),
        drafts_by_strategy: dict["Strategy", list[EventDraft]] | None = None,
        drafts_by_ledger: dict["Ledger", list[EventDraft]] | None = None,
        audit_contract: bool = False,
        enforce_contract: bool = False,
    ) -> None:
        self.timestamp = timestamp
        self.active_strategies = active_strategies
        self.active_ledgers = active_ledgers
        # A strategy can have multiple simultaneous drafts in one dispatch
        # batch (e.g. several ORDER events for different products firing at
        # the same timestamp) -- always a list, never collapsed to one.
        self._drafts_by_strategy: dict["Strategy", list[EventDraft]] = drafts_by_strategy or {}
        self._drafts_by_ledger: dict["Ledger", list[EventDraft]] = drafts_by_ledger or {}
        self._event_queue = event_queue
        self._values: dict["FieldRef", Any] = {}
        self._values_by_strategy: dict["FieldRef", dict["Strategy", Any]] = {}
        self._audit_contract = audit_contract
        self._enforce_contract = enforce_contract
        self._active_flow: ResolvedFlow | None = None
        self._contract_violations: list[dict[str, Any]] = []
        self._warned_contract_violations: set[tuple[str, str, str]] = set()

    def get(self, ref: "FieldRef", default: Any = None) -> Any:
        self._record_contract_access("read", ref)
        return self._values.get(ref, default)

    def set(self, ref: "FieldRef", value: Any) -> None:
        self._record_contract_access("write", ref)
        self._values[ref] = value
        self._push_if_event(value)

    def get_for(self, ref: "FieldRef", strategy: "Strategy", default: Any = None) -> Any:
        self._record_contract_access("read", ref)
        return self._values_by_strategy.get(ref, {}).get(strategy, default)

    def set_for(self, ref: "FieldRef", strategy: "Strategy", value: Any) -> None:
        self._record_contract_access("write", ref)
        self._values_by_strategy.setdefault(ref, {})[strategy] = value
        self._push_if_event(value)

    def enter_flow(self, flow: ResolvedFlow) -> None:
        self._active_flow = flow

    def exit_flow(self) -> None:
        self._active_flow = None

    def contract_violations(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._contract_violations)

    def _record_contract_access(self, access: str, ref: "FieldRef") -> None:
        if not self._audit_contract and not self._enforce_contract:
            return
        flow = self._active_flow
        if flow is None:
            return
        declared = flow.inputs if access == "read" else flow.outputs
        if ref in declared:
            return
        violation = {
            "flow": _flow_qualified_name(flow),
            "phase": flow.phase.value,
            "event_kind": flow.event_kind.name if flow.event_kind is not None else "",
            "access": access,
            "field": ref.qualified_name,
        }
        self._contract_violations.append(violation)
        if self._enforce_contract:
            raise SchedulerError(
                f"flow {_flow_qualified_name(flow)!r} performed undeclared {access} "
                f"of field {ref.qualified_name!r}"
            )
        warn_key = (_flow_qualified_name(flow), access, ref.qualified_name)
        if warn_key not in self._warned_contract_violations:
            self._warned_contract_violations.add(warn_key)
            warnings.warn(
                f"flow {_flow_qualified_name(flow)!r} performed undeclared {access} "
                f"of field {ref.qualified_name!r}",
                RuntimeWarning,
                stacklevel=3,
            )

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

    def payloads_for_ledger(self, ledger: "Ledger") -> list[Any]:
        """All payloads for this ledger in this dispatch batch.

        Ledger-scoped events intentionally do not require a strategy carrier.
        Strategy routing remains available separately only to gate which flows
        are active for the strategies attached to this ledger.
        """
        from .ledger import ledger_identity

        return [draft.payload for draft in self._drafts_by_ledger.get(ledger_identity(ledger), ())]

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
        state: "BacktestRunState",
        callback: Callable[[int, int, str], None] | None,
        activity_sink: ProgressSink | None,
        event_queue: EventQueue,
        flow_strategies: dict[str, frozenset["Strategy"]] | None = None,
    ) -> None:
        self._state = state
        self._callback = callback
        self._activity_sink = activity_sink
        self._event_queue = event_queue
        self._flow_strategies = flow_strategies or {}
        self._completed = 0
        self._signal_total = 0
        self._signal_completed = 0
        self._pre_total = 0
        self._pre_completed = 0
        self._post_total = 0
        self._post_completed = 0

    def emit_manifest(
        self,
        groups: dict[tuple[Phase, EventKind | None], list[ResolvedFlow]],
        state: "BacktestRunState",
        flow_strategies: dict[str, frozenset["Strategy"]],
    ) -> None:
        if self._activity_sink is not None:
            self._activity_sink.emit_activity_manifest(activity_manifest_from_groups(groups, state, flow_strategies))

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

    def activity(
        self,
        flow: ResolvedFlow,
        *,
        timestamp: pd.Timestamp | None,
        phase: str | None = None,
        strategies: frozenset["Strategy"] | None = None,
    ) -> None:
        if self._activity_sink is None:
            return
        activity_phase = phase or _activity_phase_for_flow(flow)
        ts_text = timestamp.isoformat() if timestamp is not None else ""
        active_strategies = strategies or _strategies_using_flow(self._state, flow.name, self._flow_strategies)
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
            mode_info=_mode_info_for_flow(self._state, flow, active_strategies),
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
    state: "BacktestRunState",
    event_queue: EventQueue,
    tracker: "_ProgressTracker | None" = None,
    audit_contract: bool = False,
    enforce_contract: bool = False,
    flow_strategies: dict[str, frozenset["Strategy"]] | None = None,
) -> Callable[[list[EventDraft]], None]:
    applicable_by_flow = flow_strategies or _flow_strategy_sets(state, ordered_flows)

    def handler(batch: list[EventDraft]) -> None:
        timestamp = batch[0].timestamp
        # A strategy can appear more than once in one batch (e.g. several
        # ORDER events for different products at the same timestamp) --
        # group by strategy without dropping any draft. One pass, O(batch).
        drafts_by_strategy: dict["Strategy", list[EventDraft]] = {}
        drafts_by_ledger: dict[Any, list[EventDraft]] = {}
        ledger_active_strategies: set["Strategy"] = set()
        for draft in batch:
            if draft.strategy is not None:
                drafts_by_strategy.setdefault(draft.strategy, []).append(draft)
            if draft.ledger is not None:
                drafts_by_ledger.setdefault(draft.ledger, []).append(draft)
                ledger_active_strategies.update(_strategies_for_ledger(state, draft.ledger))
            if draft.strategy is None and draft.ledger is None:
                raise SchedulerError(
                    f"{draft.kind.name} event at {draft.timestamp} has neither strategy nor ledger"
                )
        all_active = frozenset(set(drafts_by_strategy) | ledger_active_strategies)
        all_active_ledgers = frozenset(drafts_by_ledger)
        # ONE ctx for the whole batch -- this is what lets one Flow's
        # ctx.set_for(...) be read by a later Flow in the same batch (e.g.
        # LedgerModule.equity_on_signal -> OrderBookModule.size_order).
        # active_strategies is narrowed per Flow call (different Flows can
        # apply to different subsets), but _values/_values_by_strategy
        # persist across the whole batch.
        ctx = FlowContext(
            timestamp=timestamp, event_queue=event_queue,
            active_strategies=all_active, active_ledgers=all_active_ledgers,
            drafts_by_strategy=drafts_by_strategy,
            drafts_by_ledger=drafts_by_ledger,
            audit_contract=audit_contract,
            enforce_contract=enforce_contract,
        )
        for f in ordered_flows:
            applicable = all_active & applicable_by_flow.get(f.name, frozenset())
            if not applicable:
                continue
            ctx.active_strategies = applicable
            if tracker is not None:
                tracker.activity(f, timestamp=timestamp, phase="event_replay", strategies=applicable)
            _compute_flow(f, state, ctx)
            if tracker is not None:
                tracker.tick(f.effective_description, phase=f.phase)
        if tracker is not None and batch and batch[0].kind is EventKind.SIGNAL:
            tracker.signal_batch_done(len(batch))
    return handler


def _strategies_for_ledger(state: "BacktestRunState", ledger: Any) -> frozenset["Strategy"]:
    from .ledger import ledger_identity
    from tools.testers.backtest.modules.strategy_book import strategy_book_store_for

    target = ledger_identity(ledger)
    store = strategy_book_store_for(state)
    strategies: set["Strategy"] = set()
    for strategy in state.strategy_configs:
        if target in store.ledgers_for_strategy(state, strategy):
            strategies.add(strategy)
    return frozenset(strategies)


def _flow_strategy_sets(
    state: "BacktestRunState",
    flows: list[ResolvedFlow] | tuple[ResolvedFlow, ...],
) -> dict[str, frozenset["Strategy"]]:
    flow_names = {flow.name for flow in flows}
    result: dict[str, set["Strategy"]] = {name: set() for name in flow_names}
    for strategy, config in state.strategy_configs.items():
        for flow_name in config.active_flow_names & flow_names:
            result.setdefault(flow_name, set()).add(strategy)
    return {name: frozenset(strategies) for name, strategies in result.items()}


def _all_flow_strategy_sets(
    state: "BacktestRunState",
    groups: dict[tuple[Phase, EventKind | None], list[ResolvedFlow]],
) -> dict[str, frozenset["Strategy"]]:
    flows: list[ResolvedFlow] = []
    for ordered_flows in groups.values():
        flows.extend(ordered_flows)
    return _flow_strategy_sets(state, flows)


def _strategies_using_flow(
    state: "BacktestRunState",
    flow_name: str,
    flow_strategies: dict[str, frozenset["Strategy"]] | None = None,
) -> frozenset["Strategy"]:
    if flow_strategies is not None:
        return flow_strategies.get(flow_name, frozenset())
    return frozenset(
        strategy for strategy in state.strategy_configs
        if flow_name in state.config_for(strategy).active_flow_names
    )


def _pre_post_applicable_strategies(
    state: "BacktestRunState",
    flow: ResolvedFlow,
    flow_strategies: dict[str, frozenset["Strategy"]] | None = None,
) -> frozenset["Strategy"]:
    return _strategies_using_flow(state, flow.name, flow_strategies)


_MODE_FIELD_SUFFIXES = ("_mode", "_method", "_policy")
_MODE_FIELD_NAMES = {
    "engine_mode",
    "accounting_mode",
    "cost_basis_method",
    "money_calculation_policy",
    "factor_mode",
    "warmup_mode",
    "freq_mode",
    "freq_fixed",
    "data_source_mode",
    "data_sources",
    "margin_mode",
    "fee_mode",
    "liquidity_mode",
    "slippage_mode",
    "allocation_mode",
    "rebalance_event_mode",
    "equity_compute_live",
    "matching_model",
}
_SKIP_MODE_FIELD_NAMES = {
    "factor_candidates",
    "product_path_candidates",
    "product_path_selection",
    "factor",
}


def _mode_info_for_flow(
    state: "BacktestRunState",
    flow: ResolvedFlow,
    strategies: frozenset["Strategy"],
) -> dict[str, Any]:
    if not strategies:
        return {}
    values_by_name: dict[str, set[str]] = {}
    for strategy in strategies:
        config = state.config_for(strategy)
        for ref, value in config.field_values.items():
            name = str(getattr(ref, "name", ref) or "")
            if not _is_mode_field(name):
                continue
            owner = str(getattr(ref, "owner", "") or "")
            if owner and flow.owner and owner not in {flow.owner, "EngineModule", "MarketDataModule"}:
                # Keep global run modes plus the flow owner's own modes; this
                # keeps the fixed CLI line compact while still diagnosing why
                # the current flow chose a branch.
                continue
            values_by_name.setdefault(name, set()).add(_mode_value_text(value))
    mode_info: dict[str, Any] = {}
    for name in sorted(values_by_name):
        values = sorted(values_by_name[name])
        mode_info[name] = values[0] if len(values) == 1 else f"多值[{len(values)}]"
    return mode_info


def _is_mode_field(name: str) -> bool:
    if not name or name in _SKIP_MODE_FIELD_NAMES:
        return False
    return name in _MODE_FIELD_NAMES or name.endswith(_MODE_FIELD_SUFFIXES)


def _mode_value_text(value: Any) -> str:
    if value is None:
        return "None"
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    if isinstance(value, (list, tuple, set, frozenset)):
        return f"{len(value)}项"
    if isinstance(value, dict):
        return f"{len(value)}项"
    return type(value).__name__


def run(
    state: "BacktestRunState",
    event_queue: EventQueue,
    resolved_flows: list[ResolvedFlow],
    progress: Callable[[int, int, str], None] | None = None,
    activity_sink: ProgressSink | None = None,
    audit_flow_contract: bool = False,
    enforce_flow_contract: bool = False,
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
    flow_strategies = _all_flow_strategy_sets(state, groups)
    tracker = _ProgressTracker(state, progress, activity_sink, event_queue, flow_strategies)
    tracker.emit_manifest(groups, state, flow_strategies)
    applicable_pre_flows = [
        f for f in pre_replay_flows
        if _pre_post_applicable_strategies(state, f, flow_strategies)
    ]
    applicable_post_flows = [
        f for f in post_replay_flows
        if _pre_post_applicable_strategies(state, f, flow_strategies)
    ]
    tracker.set_phase_totals(pre_total=len(applicable_pre_flows), post_total=len(applicable_post_flows))

    for (phase, event_kind), ordered_flows in groups.items():
        if phase is Phase.PER_EVENT:
            event_queue.set_dispatcher(
                cast(EventKind, event_kind),
                make_dispatcher(
                    ordered_flows,
                    state,
                    event_queue,
                    tracker,
                    audit_flow_contract,
                    enforce_flow_contract,
                    flow_strategies,
                ),
            )

    ctx = FlowContext(
        timestamp=None,
        event_queue=event_queue,
        audit_contract=audit_flow_contract,
        enforce_contract=enforce_flow_contract,
    )
    for f in pre_replay_flows:
        applicable = _pre_post_applicable_strategies(state, f, flow_strategies)
        if not applicable:
            continue
        ctx.active_strategies = applicable
        tracker.activity(f, timestamp=None, phase="pre_replay", strategies=applicable)
        _compute_flow(f, state, ctx)
        tracker.phase_flow_done(phase="pre_replay")
        tracker.tick(f.effective_description, phase=Phase.PRE_REPLAY)

    tracker.note_signal_queue_ready()
    event_queue.run_until_drained()
    tracker.event_replay_done()

    ctx = FlowContext(
        timestamp=None,
        event_queue=event_queue,
        audit_contract=audit_flow_contract,
        enforce_contract=enforce_flow_contract,
    )
    for f in post_replay_flows:
        applicable = _pre_post_applicable_strategies(state, f, flow_strategies)
        if not applicable:
            continue
        ctx.active_strategies = applicable
        tracker.activity(f, timestamp=None, phase="post_replay", strategies=applicable)
        _compute_flow(f, state, ctx)
        tracker.phase_flow_done(phase="post_replay")
        tracker.tick(f.effective_description, phase=Phase.POST_REPLAY)
    tracker.complete()


def _compute_flow(flow: ResolvedFlow, state: "BacktestRunState", ctx: FlowContext) -> None:
    ctx.enter_flow(flow)
    try:
        flow.compute(state, ctx)
    finally:
        ctx.exit_flow()


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
    state: "BacktestRunState",
    flow_strategies: dict[str, frozenset["Strategy"]] | None = None,
) -> list[dict[str, Any]]:
    phase_specs: list[dict[str, Any]] = []
    pre_all = [
        flow for flow in groups.get((Phase.PRE_REPLAY, None), ())
        if _flow_applicable_to_any_strategy(state, flow, flow_strategies)
    ]
    phase_specs.append(_phase_spec("pre_replay", pre_all))

    event_flows: list[ResolvedFlow] = []
    for (phase, _kind), flows in groups.items():
        if phase is Phase.PER_EVENT:
            event_flows.extend(
                flow for flow in flows
                if _flow_applicable_to_any_strategy(state, flow, flow_strategies)
            )
    event_flows = sorted(event_flows, key=lambda f: (f.order, f.event_kind or EventKind.SIGNAL, f.name))
    event_flows = _dedupe_manifest_flows(event_flows)
    phase_specs.append(_phase_spec("event_replay", event_flows))

    post = [
        flow for flow in groups.get((Phase.POST_REPLAY, None), ())
        if _flow_applicable_to_any_strategy(state, flow, flow_strategies)
    ]
    phase_specs.append(_phase_spec("post_replay", post))
    return phase_specs


def _flow_applicable_to_any_strategy(
    state: "BacktestRunState",
    flow: ResolvedFlow,
    flow_strategies: dict[str, frozenset["Strategy"]] | None = None,
) -> bool:
    return bool(_strategies_using_flow(state, flow.name, flow_strategies))


def _dedupe_manifest_flows(flows: list[ResolvedFlow]) -> list[ResolvedFlow]:
    result: list[ResolvedFlow] = []
    seen: set[str] = set()
    for flow in flows:
        # A logical flow can be registered under multiple event kinds (for
        # example live factor handling observes BAR events and publishes SIGNAL
        # values). The progress diagram should show the logical user-facing
        # operation once.
        key = flow.name
        if key in seen:
            continue
        seen.add(key)
        result.append(flow)
    return result


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
