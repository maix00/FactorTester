"""Optional profiling hooks for the native backtest engine.

The scheduler must remain profiling-free unless a caller explicitly injects a
profiler.  This module owns clocks, accumulation, and runtime-info rendering so
alternative profilers can be supplied without changing scheduler semantics.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    import pandas as pd

    from tools.testers.backtest.engines.native.scheduler import ResolvedFlow
    from tools.testers.backtest.engines.native.state import BacktestRunState
    from tools.testers.backtest.engines.native.strategy import Strategy


class BacktestProfiler(Protocol):
    """Profiler plug-in consumed by the scheduler and result assembler."""

    def begin_flow(self, flow: "ResolvedFlow") -> object: ...

    def end_flow(
        self,
        token: object,
        flow: "ResolvedFlow",
        *,
        timestamp: "pd.Timestamp | None",
        strategies: frozenset["Strategy"] | None,
    ) -> None: ...

    def flush_flows(self, state: "BacktestRunState") -> None: ...

    def reset(self) -> None: ...

    def begin_stage(self, name: str) -> object: ...

    def end_stage(
        self,
        token: object,
        state: "BacktestRunState",
        *,
        name: str,
        details: dict[str, Any],
    ) -> None: ...


@dataclass(slots=True)
class _FlowAccumulator:
    flow: "ResolvedFlow"
    count: int = 0
    last_ms: float = 0.0
    total_ms: float = 0.0
    max_ms: float = 0.0
    strategy_count: int = 0
    timestamp: "pd.Timestamp | None" = None


class CumulativeBacktestProfiler:
    """Low-overhead cumulative profiler explicitly enabled by a caller."""

    def __init__(
        self,
        *,
        min_duration_ms: float = 1000.0,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.min_duration_ms = max(0.0, float(min_duration_ms))
        self._clock = clock
        self._flows: dict[int, _FlowAccumulator] = {}

    def begin_flow(self, flow: "ResolvedFlow") -> object:
        del flow
        return self._clock()

    def end_flow(
        self,
        token: object,
        flow: "ResolvedFlow",
        *,
        timestamp: "pd.Timestamp | None",
        strategies: frozenset["Strategy"] | None,
    ) -> None:
        elapsed_ms = (self._clock() - float(token)) * 1000.0
        accumulator = self._flows.get(id(flow))
        if accumulator is None:
            accumulator = _FlowAccumulator(flow=flow)
            self._flows[id(flow)] = accumulator
        accumulator.count += 1
        accumulator.last_ms = elapsed_ms
        accumulator.total_ms += elapsed_ms
        accumulator.max_ms = max(accumulator.max_ms, elapsed_ms)
        accumulator.strategy_count = max(
            accumulator.strategy_count,
            len(strategies) if strategies is not None else 0,
        )
        if timestamp is not None:
            accumulator.timestamp = timestamp

    def flush_flows(self, state: "BacktestRunState") -> None:
        try:
            from tools.testers.backtest.modules.runtime_info import record_runtime_info
        except Exception:
            self._flows.clear()
            return
        for accumulator in self._flows.values():
            total_ms = accumulator.total_ms
            if total_ms < self.min_duration_ms:
                continue
            flow = accumulator.flow
            count = accumulator.count
            phase = "event_replay" if flow.phase.value == "per_event" else flow.phase.value
            event_kind = flow.event_kind.name if flow.event_kind is not None else "once"
            details = {
                "phase": phase,
                "event_kind": event_kind,
                "flow": flow.name,
                "owner": flow.owner,
                "label": flow.effective_description,
                "count": count,
                "elapsed_ms": round(accumulator.last_ms, 3),
                "total_ms": round(total_ms, 3),
                "max_ms": round(accumulator.max_ms, 3),
                "avg_ms": round(total_ms / count, 3),
                "strategy_count": accumulator.strategy_count,
                "timestamp": accumulator.timestamp.isoformat() if accumulator.timestamp is not None else "",
            }
            record_runtime_info(
                state,
                code="backtest_flow_profile",
                type="性能",
                status="profiled",
                level="info",
                message=f"{phase} {flow.effective_description} 累计耗时 {total_ms:.1f}ms",
                detail=(
                    f"{phase}/{event_kind}/{flow.owner}.{flow.name} 累计耗时 "
                    f"{total_ms:.1f}ms；累计 {count} 次，平均 {total_ms / count:.3f}ms。"
                ),
                details=details,
                aggregation_key=f"{phase}|{event_kind}|{flow.owner}|{flow.name}",
            )
        self._flows.clear()

    def reset(self) -> None:
        self._flows.clear()

    def begin_stage(self, name: str) -> object:
        del name
        return self._clock()

    def end_stage(
        self,
        token: object,
        state: "BacktestRunState",
        *,
        name: str,
        details: dict[str, Any],
    ) -> None:
        elapsed_ms = (self._clock() - float(token)) * 1000.0
        if elapsed_ms < self.min_duration_ms:
            return
        from tools.testers.backtest.modules.runtime_info import record_runtime_info

        payload = {**details, "phase": name, "elapsed_ms": round(elapsed_ms, 3)}
        record_runtime_info(
            state,
            code=f"backtest_{name}_profile",
            type="性能",
            status="profiled",
            level="info",
            message=f"{name} 耗时 {elapsed_ms:.1f}ms",
            detail=f"native backtest {name} 耗时 {elapsed_ms:.1f}ms。",
            details=payload,
            aggregation_key=f"{name}|native",
        )
