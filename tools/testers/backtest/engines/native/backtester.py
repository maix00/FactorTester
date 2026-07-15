"""run_backtest_task -- the "backtester" FactorTester.dispatch("backtest",
...) calls. Given a BacktestRunState already built by
strategy_config_builder.apply_strategy_configs, runs the whole engine and
shapes the result into the `execution` dict that
server/modules/single_factor_test/group.py's `_serialize_event_execution`/
`_event_group_snapshot`/`_event_group_detail`/`_event_group_ranking_detail`
already know how to read -- that contract predates this function and is
not changed here.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Callable, cast

import pandas as pd

from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowRegistry, ProgressSink, run
from tools.testers.backtest.modules.equity_curve import (
    display_equity_curve_for,
    equity_curve_for,
    margin_curve_for,
    notional_curve_for,
    position_curve_for,
)
from tools.testers.backtest.modules.engine import EngineModule
from tools.testers.backtest.modules.group_membership import target_trace_for
from tools.testers.backtest.modules.registry import _ALL_MODULE_CLASSES

if TYPE_CHECKING:
    from tools.factors.factor_tester_state import FactorTesterState
    from tools.testers.backtest.engines.native.state import BacktestRunState


def _build_registry() -> FlowRegistry:
    registry = FlowRegistry()
    for cls in _ALL_MODULE_CLASSES:
        for flow in getattr(cls, "flows", ()):
            registry.register_flow(flow)
    return registry


def run_backtest_task(
    state: "FactorTesterState",
    *,
    run_state: "BacktestRunState",
    group_owner: list[dict[str, Any]],
    settings_by_strategy: dict[str, dict[str, Any]],
    run_id: str,
    progress: Callable[[int, int, str], None] | None = None,
    activity_sink: ProgressSink | None = None,
    step_mode: bool = False,
    step_callback: "Callable[[dict[str, Any]], None] | None" = None,
) -> dict[str, Any]:
    """Fixed task: runs the engine against an already-built BacktestRunState,
    stores it on `state.account` for later snapshot/detail requests, and
    returns the `execution` dict shape group.py already consumes."""
    requested_engine = _requested_engine(run_state)
    if requested_engine != "native":
        # ADR-030: external frameworks never enter the native event queue —
        # the bridge runs shared PRE_REPLAY preparation, then the framework's
        # own loop inside its isolated worker process.
        from tools.testers.backtest.engines.workers.bridge import run_framework_backtest_task

        return run_framework_backtest_task(
            state,
            run_state=run_state,
            engine=requested_engine,
            group_owner=group_owner,
            settings_by_strategy=settings_by_strategy,
            run_id=run_id,
            progress=progress,
            activity_sink=activity_sink,
        )
    registry = _build_registry()
    queue = EventQueue()
    run(
        run_state,
        queue,
        registry.resolve(),
        progress=progress,
        activity_sink=activity_sink,
        audit_flow_contract=step_mode,
        step_mode=step_mode,
        step_callback=step_callback,
    )

    assembly_started_at = time.perf_counter()
    by_alias = {strategy.alias: strategy for strategy in run_state.strategy_configs}
    portfolios: dict[str, Any] = {}
    target_trace: dict[str, Any] = {}
    for group_id, strategy in by_alias.items():
        curve = equity_curve_for(run_state, strategy)
        display_curve = display_equity_curve_for(run_state, strategy)
        portfolios[group_id] = {
            "equity_curve": {pd.Timestamp(cast(Any, ts)).isoformat(): float(value) for ts, value in curve.items()},
            "display_equity_curve": {
                pd.Timestamp(cast(Any, ts)).isoformat(): float(value)
                for ts, value in display_curve.items()
            },
            "position_curve": position_curve_for(run_state, strategy),
            "notional_curve": notional_curve_for(run_state, strategy),
            "margin_curve": margin_curve_for(run_state, strategy),
            "execution_trace": run_state.order_flow_store.records_for_strategy(strategy),
            "initial_value": float(curve.iloc[0]) if not curve.empty else 0.0,
            "market_rule_approximation_count": 0,
        }
        target_trace[group_id] = target_trace_for(run_state, strategy)
    _record_result_assembly_profile(
        run_state,
        elapsed_ms=(time.perf_counter() - assembly_started_at) * 1000.0,
        strategy_count=len(by_alias),
        portfolio_count=len(portfolios),
    )

    state.account = run_state
    return {
        "run_id": run_id,
        "engine_result": {
            "engine": "native",
            "portfolios": portfolios,
            "target_trace": target_trace,
            "strategy_diagnostics": {},
            "event_count": queue.pending_count(),
        },
        "group_owner": group_owner,
        "settings_by_strategy": settings_by_strategy,
        "payload": {"run_id": run_id, "instruments": [], "market_rules": {}},
        "signal_kind": "native",
    }


def _requested_engine(run_state: "BacktestRunState") -> str:
    configs = getattr(run_state, "strategy_configs", {}) or {}
    values = {
        str(config.get(EngineModule.engine, "native") or "native").lower()
        for config in configs.values()
    }
    if len(values) > 1:
        raise ValueError(f"backtest strategies disagree on execution engine: {sorted(values)}")
    return next(iter(values), "native")


def _record_result_assembly_profile(
    run_state: "BacktestRunState",
    *,
    elapsed_ms: float,
    strategy_count: int,
    portfolio_count: int,
) -> None:
    raw_threshold = getattr(run_state, "backtest_profile_min_duration_ms", 1000.0)
    try:
        threshold_ms = max(0.0, float(raw_threshold))
    except (TypeError, ValueError):
        threshold_ms = 1000.0
    if elapsed_ms < threshold_ms:
        return
    try:
        from tools.testers.backtest.modules.runtime_info import record_runtime_info
    except Exception:
        return
    record_runtime_info(
        run_state,
        code="backtest_result_assembly_profile",
        type="性能",
        status="profiled",
        level="info",
        message=f"结果组装耗时 {elapsed_ms:.1f}ms",
        detail=(
            f"native replay 完成后的 portfolio/target trace/result dict "
            f"组装耗时 {elapsed_ms:.1f}ms。"
        ),
        details={
            "phase": "result_assembly",
            "elapsed_ms": round(float(elapsed_ms), 3),
            "strategy_count": int(strategy_count),
            "portfolio_count": int(portfolio_count),
        },
        aggregation_key="result_assembly|native",
    )
