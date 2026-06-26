"""Event-driven pipeline stages registered by setting modules.

Each stage corresponds to a SettingModule.execution_stage value.
The runner subscribes to MARKET_SLICE_CLOSED and dispatches through the
stage pipeline — it never iterates timestamps directly, never hardcodes
module names or field names.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd

from .runtime import (
    EventDraft,
    EventEnvelope,
    EventRuntime,
    EventTopic,
    MarketSlice,
)


class ExecutionStage(Enum):
    """Processing phases dispatched on every MARKET_SLICE_CLOSED.

    Enum order defines the fixed phase sequence. Within each phase,
    modules execute in topological order determined by their PhaseHandler
    before/after declarations.
    """

    # --- Pre-slice (called once before market data replay) ---
    PRE_REPLAY = "pre_replay"

    # --- Per-slice (called on every MARKET_SLICE_CLOSED) ---
    FACTOR = "factor"
    TARGET_GENERATION = "target_generation"
    RISK = "risk"
    ORDER_SIZING = "order_sizing"
    ORDER_EXECUTION = "order_execution"
    ORDER_MATCHING = "order_matching"
    ORDER_FILL_ACCOUNTING = "order_fill_accounting"
    ACCOUNTING = "accounting"
    REPORT = "report"

    # --- Post-replay (called after all slices) ---
    POST_REPLAY = "post_replay"


# Stage name to enum — used to map SettingModule.execution_stage strings
_STAGE_BY_NAME: dict[str, ExecutionStage] = {s.value: s for s in ExecutionStage}


def resolve_stage(name: str) -> ExecutionStage:
    if not name:
        return ExecutionStage.REPORT  # modules without stage are report-only
    if name not in _STAGE_BY_NAME:
        raise ValueError(f"unknown execution stage: {name!r}")
    return _STAGE_BY_NAME[name]


# ── PhaseHandler: module-side declaration ──────────────────────────


@dataclass(frozen=True, slots=True)
class PhaseHandler:
    """Declares what one SettingModule needs/produces/records in one phase.

    Used by the runner to:
      - topologically sort modules within a phase (via `before` / `after`)
      - validate that field contracts are satisfied
      - route signals for feedback loops
    """

    phase: str
    order: int = 100
    before: tuple[str, ...] = ()   # module keys that must run AFTER this one
    after: tuple[str, ...] = ()    # module keys that must run BEFORE this one
    needs: tuple[str, ...] = ()    # fields this module reads
    produces: tuple[str, ...] = () # fields this module writes
    records: tuple[str, ...] = ()  # fields this module records to trace


# ── PhaseContext: per-slice mutable state ──────────────────────────


@dataclass
class PhaseContext:
    """Mutable per-slice context that phase handlers read from and write to.

    This is the sole shared state between modules within one timestamp.
    Modules communicate exclusively through this context — never by
    calling each other directly.

    Signals allow feedback loops: a downstream module can request
    re-execution of upstream modules (e.g. cash constraint causes
    rescaling of deltas).
    """

    # --- Shared run-level state ---
    request: Any  # TargetWeightInput
    memberships: np.ndarray
    updates: np.ndarray
    calculators: tuple[Any, ...]  # tuple of GroupTargetCalculator

    # --- Current slice ---
    row: int = 0
    timestamp: pd.Timestamp | None = None
    current_prices: np.ndarray | None = None
    valuation_values: np.ndarray | None = None
    volumes_row: np.ndarray | None = None
    margin_ratios: np.ndarray | None = None
    volatility_snapshots: dict[Any, dict[str, float]] = field(default_factory=dict)

    # --- Per-strategy state (indexed by strategy position) ---
    strategy_states: list[dict[str, Any]] = field(default_factory=list)

    # --- Collected results ---
    portfolios: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, dict[str, Any]] = field(default_factory=dict)

    # --- Volatility estimation ---
    volatility_estimators: dict[Any, Any] = field(default_factory=dict)
    volatility_previous_prices: dict[Any, np.ndarray | None] = field(default_factory=dict)

    # --- Named field store (phase handlers use this instead of raw attributes) ---
    _fields: dict[str, Any] = field(default_factory=dict)

    # --- Feedback signals ---
    _signals: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """Read a named field from the shared context."""
        return self._fields.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Write a named field into the shared context."""
        self._fields[key] = value

    def signal(self, name: str, value: Any = True) -> None:
        """Raise a feedback signal (e.g. 'needs_rescale')."""
        self._signals[name] = value

    def consume_signal(self, name: str) -> Any:
        """Read and clear a signal."""
        return self._signals.pop(name, None)

    def has_signal(self, name: str) -> bool:
        return name in self._signals

    @property
    def pending_signals(self) -> tuple[str, ...]:
        return tuple(self._signals.keys())


# A stage handler is called per-slice (or once for pre/post).
# It mutates PhaseContext and may publish EventDraft into the runtime.
StageHandler = Callable[
    [PhaseContext, EventEnvelope, EventRuntime],
    EventDraft | Sequence[EventDraft] | None,
]


# ── Topological sort for module ordering within a phase ────────────


def _topological_sort(
    modules: Sequence[str],
    before_map: dict[str, set[str]],
    after_map: dict[str, set[str]],
) -> list[str]:
    """Kahn's algorithm respecting before/after constraints.

    `before_map[m]` = modules that must run AFTER m.
    `after_map[m]`  = modules that must run BEFORE m.

    Ties are broken by insertion order (stable).
    """
    in_degree: dict[str, int] = {m: 0 for m in modules}
    adj: dict[str, list[str]] = {m: [] for m in modules}

    for m in modules:
        for after_m in before_map.get(m, ()):
            adj[m].append(after_m)
            in_degree[after_m] = in_degree.get(after_m, 0) + 1
        for before_m in after_map.get(m, ()):
            adj[before_m].append(m)
            in_degree[m] = in_degree.get(m, 0) + 1

    queue = [m for m in modules if in_degree[m] == 0]
    result: list[str] = []
    while queue:
        node = queue.pop(0)
        result.append(node)
        for neighbor in adj[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(result) != len(modules):
        raise ValueError(
            f"circular dependency detected among phase modules: {set(modules) - set(result)}"
        )
    return result


# ── RegisteredStage + StagePipeline ─────────────────────────────────


@dataclass
class RegisteredStage:
    """One stage entry registered by a setting module."""

    stage: ExecutionStage
    order: int
    module_key: str
    handler: StageHandler


class StagePipeline:
    """Ordered collection of phases, with topological module order inside each.

    Built from SettingModule registrations. The runner calls:
      - pre_replay() once before the event loop
      - per_slice() on every MARKET_SLICE_CLOSED event
      - post_replay() once after the event loop
    """

    def __init__(self) -> None:
        self._stages: list[RegisteredStage] = []
        self._sorted: bool = True

    def register(
        self,
        stage: ExecutionStage,
        order: int,
        module_key: str,
        handler: StageHandler,
    ) -> None:
        self._stages.append(RegisteredStage(stage, order, module_key, handler))
        self._sorted = False

    def build(
        self,
        module_phases: Mapping[str, tuple[PhaseHandler, ...]],
        module_order: Mapping[str, int],
    ) -> None:
        """Topologically sort modules within each phase using PhaseHandler
        before/after declarations, while keeping phase-level ordering by
        ExecutionStage enum order.

        Called once after all modules are registered, before the run starts.
        """
        stage_order = list(ExecutionStage)
        per_phase: dict[ExecutionStage, list[RegisteredStage]] = defaultdict(list)
        for s in self._stages:
            per_phase[s.stage].append(s)

        self._stages.clear()
        for es in stage_order:
            entries = per_phase.get(es)
            if not entries:
                continue
            module_keys = [e.module_key for e in entries]
            before_map: dict[str, set[str]] = {}
            after_map: dict[str, set[str]] = {}
            for mk in module_keys:
                handlers = module_phases.get(mk, ())
                for ph in handlers:
                    if ph.phase == es.value:
                        before_map[mk] = set(ph.before)
                        after_map[mk] = set(ph.after)
                        break
            try:
                sorted_keys = _topological_sort(module_keys, before_map, after_map)
            except ValueError:
                # fallback: stable sort by module order
                sorted_keys = sorted(module_keys, key=lambda k: module_order.get(k, 100))

            key_to_entry = {e.module_key: e for e in entries}
            for mk in sorted_keys:
                if mk in key_to_entry:
                    self._stages.append(key_to_entry[mk])
        self._sorted = True

    def pre_replay(self, ctx: PhaseContext, runtime: EventRuntime) -> None:
        for stage in self._stages:
            if stage.stage == ExecutionStage.PRE_REPLAY:
                stage.handler(ctx, None, runtime)  # type: ignore[arg-type]

    def per_slice(self, ctx: PhaseContext, event: EventEnvelope, runtime: EventRuntime) -> None:
        """Execute every per-slice phase handler in order.

        After all phases run, check for feedback signals. If any module
        raised a signal, re-run the affected phases (limited to prevent
        infinite loops).
        """
        per_slice_stages = [
            s for s in self._stages
            if s.stage not in (ExecutionStage.PRE_REPLAY, ExecutionStage.POST_REPLAY)
        ]
        max_iterations = 3
        for _ in range(max_iterations):
            # Re-evaluate which stages to run (signals may change this)
            stages_to_run = per_slice_stages
            for stage in stages_to_run:
                stage.handler(ctx, event, runtime)
            if not ctx.pending_signals:
                break
            # Consume all signals for next iteration
            ctx._signals.clear()
        else:
            if ctx.pending_signals:
                ctx._signals.clear()  # don't leak signals across slices

    def post_replay(self, ctx: PhaseContext, runtime: EventRuntime) -> None:
        for stage in self._stages:
            if stage.stage == ExecutionStage.POST_REPLAY:
                stage.handler(ctx, None, runtime)  # type: ignore[arg-type]

    @property
    def stage_keys(self) -> tuple[str, ...]:
        return tuple(f"{s.module_key}:{s.stage.value}" for s in self._stages)
