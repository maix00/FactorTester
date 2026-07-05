"""Framework execution bridge (ADR-030): non-native engines run themselves.

``run_backtest_task`` routes every non-native engine here. The bridge never
builds a native event replay: it executes only the PRE_REPLAY flows (market
data load, factor precompute, run-window/term-structure resolution — the
shared preparation semantics), translates the prepared state into the worker
payload, dispatches to the framework's isolated worker process, forwards
``GTHT_PROGRESS`` lines into the frontend ProgressSink, and wraps the worker
result into the same ``execution`` dict shape native returns.
"""

from __future__ import annotations

import threading
import uuid
from typing import TYPE_CHECKING, Any, Callable

import pandas as pd

from tools.testers.backtest.engines.cancellation import BacktestCancelled
from tools.testers.backtest.engines.native.scheduler import (
    EventQueue,
    FlowContext,
    FlowRegistry,
    Phase,
    ProgressSink,
    _all_flow_strategy_sets,
    _compute_flow,
    _phase_spec,
    _pre_post_applicable_strategies,
    sort_and_validate,
)
from tools.testers.backtest.engines.workers.contracts import WorkerRequest
from tools.testers.backtest.engines.workers.dispatcher import EngineWorkerDispatcher
from tools.testers.backtest.engines.workers.translator import (
    build_membership_payload,
    translate_market_payload,
    translate_strategy_configs,
)
from tools.testers.backtest.modules.registry import _ALL_MODULE_CLASSES

if TYPE_CHECKING:
    from tools.factors.factor_tester_state import FactorTesterState
    from tools.testers.backtest.engines.native.state import BacktestRunState


_SUPPORTED_ENGINES = ("backtrader", "qlib", "zipline", "rqalpha")
_ENGINE_LABELS = {
    "backtrader": "Backtrader",
    "qlib": "Qlib",
    "zipline": "Zipline",
    "rqalpha": "RQAlpha",
}


def run_framework_backtest_task(
    state: "FactorTesterState",
    *,
    run_state: "BacktestRunState",
    engine: str,
    group_owner: list[dict[str, Any]],
    settings_by_strategy: dict[str, dict[str, Any]],
    run_id: str,
    progress: Callable[[int, int, str], None] | None = None,
    activity_sink: ProgressSink | None = None,
    dispatcher: EngineWorkerDispatcher | None = None,
    timeout_seconds: float = 600.0,
) -> dict[str, Any]:
    if engine not in _SUPPORTED_ENGINES:
        raise ValueError(f"unknown framework engine: {engine!r}")
    label = _ENGINE_LABELS.get(engine, engine)

    if activity_sink is not None:
        activity_sink.emit_activity_manifest(_bridge_manifest(label))

    # ── phase 1: shared preparation via native PRE_REPLAY flows ──
    _emit_activity(activity_sink, phase="pre_replay", flow_key="framework_prepare",
                   message=f"正在为 {label} 准备数据与信号")
    _run_pre_replay_flows(run_state)

    payload = translate_market_payload(run_state)
    strategy_dialects = translate_strategy_configs(
        run_state, settings_by_strategy, framework=engine,
    )
    event_timestamps = pd.DatetimeIndex([pd.Timestamp(ts) for ts in payload["timestamps"]])
    payload.update(build_membership_payload(run_state, strategy_dialects, event_timestamps))
    payload["strategy_configs"] = strategy_dialects
    payload["initial_cash"] = max(
        (float(d.get("initial_capital") or 0.0) for d in strategy_dialects), default=0.0,
    ) or 1.0

    # ── phase 2: the framework runs its own loop in an isolated worker ──
    _emit_activity(activity_sink, phase="event_replay", flow_key="framework_replay",
                   message=f"{label} 框架回放中")
    cancel_event = threading.Event()

    def _forward_progress(update: dict[str, Any]) -> None:
        completed = int(update.get("completed") or 0)
        total = int(update.get("total") or 0)
        if activity_sink is not None and total > 0:
            activity_sink.emit_signal_progress(
                completed=completed, total=total, phase="event_replay",
            )
        if progress is not None:
            try:
                progress(completed, total, str(update.get("event_timestamp") or ""))
            except BacktestCancelled:
                cancel_event.set()

    response = (dispatcher or EngineWorkerDispatcher()).dispatch(
        WorkerRequest(
            request_id=f"{run_id}-{uuid.uuid4().hex[:8]}",
            engine=engine,
            operation="run_group_strategy",
            payload=payload,
        ),
        timeout_seconds=timeout_seconds,
        progress=_forward_progress,
        cancel_event=cancel_event,
    )

    # ── phase 3: collect ──
    _emit_activity(activity_sink, phase="post_replay", flow_key="framework_collect",
                   message=f"正在收集 {label} 结果")
    result = dict(response.result)
    state.account = run_state
    return {
        "run_id": run_id,
        "engine_result": {
            "engine": engine,
            "portfolios": result.get("portfolios", {}),
            "target_trace": result.get("target_trace", {}),
            "strategy_diagnostics": result.get("strategy_diagnostics", {}),
            "event_count": int(result.get("event_count") or 0),
        },
        "group_owner": group_owner,
        "settings_by_strategy": settings_by_strategy,
        "payload": {
            "run_id": run_id,
            "instruments": payload["instruments"],
            "market_rules": payload["market_rules"],
        },
        "signal_kind": result.get("signal_kind") or "precomputed",
    }


def _run_pre_replay_flows(run_state: "BacktestRunState") -> None:
    """Execute only PRE_REPLAY flows; events they push are never drained."""
    registry = FlowRegistry()
    for cls in _ALL_MODULE_CLASSES:
        for flow in getattr(cls, "flows", ()):
            registry.register_flow(flow)
    groups = sort_and_validate(registry.resolve())
    flow_strategies = _all_flow_strategy_sets(run_state, groups)
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    for flow in groups.get((Phase.PRE_REPLAY, None), ()):
        applicable = _pre_post_applicable_strategies(run_state, flow, flow_strategies)
        if not applicable:
            continue
        ctx.active_strategies = applicable
        _compute_flow(flow, run_state, ctx)


def _bridge_manifest(engine_label: str) -> list[dict[str, Any]]:
    """Three-phase manifest reusing native phase keys so the frontend flow
    chart renders framework runs without modification."""

    class _Pseudo:
        def __init__(self, key: str, name: str, description: str):
            self.activity_key = key
            self.name = name
            self.effective_description = description
            self.event_kind = None

    return [
        _phase_spec("pre_replay", [
            _Pseudo("framework_prepare", "framework_prepare", f"为 {engine_label} 准备数据与信号"),
        ]),
        _phase_spec("event_replay", [
            _Pseudo("framework_replay", "framework_replay", f"{engine_label} 框架回放"),
        ]),
        _phase_spec("post_replay", [
            _Pseudo("framework_collect", "framework_collect", f"收集 {engine_label} 结果"),
        ]),
    ]


def _emit_activity(sink: ProgressSink | None, *, phase: str, flow_key: str, message: str) -> None:
    if sink is None:
        return
    sink.emit_activity(phase=phase, flow_key=flow_key, flow_name=flow_key, message=message)
