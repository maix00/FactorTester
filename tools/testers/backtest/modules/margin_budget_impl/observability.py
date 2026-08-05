"""Opt-in diagnostics for execution-margin checks.

The observer is deliberately separate from the margin calculation.  A run
without an observer does not allocate counters or format runtime information.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


class MarginExecutionObserver(Protocol):
    def begin_pool(self, pool: str, order_count: int) -> object: ...
    def begin_stage(self, token: object, name: str) -> object: ...
    def end_stage(self, token: object, name: str, stage_token: object) -> None: ...
    def record_projection(self, token: object) -> None: ...
    def end_pool(self, token: object, **details: Any) -> None: ...
    def flush(self, state: Any) -> None: ...
    def reset(self) -> None: ...


@dataclass(slots=True)
class _PoolStats:
    checks: int = 0
    orders_seen: int = 0
    over_limit_checks: int = 0
    over_limit_orders: int = 0
    scaled_orders: int = 0
    projection_calls: int = 0
    scale_total: float = 0.0
    scale_min: float = 1.0
    scale_max: float = 0.0
    full_utilization: float = 0.0
    final_utilization: float = 0.0
    maximum: float = 0.0
    stage_ns: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    stage_calls: dict[str, int] = field(default_factory=lambda: defaultdict(int))


class CumulativeMarginExecutionObserver:
    """Aggregates margin-check decisions and stage timings per cash pool."""

    def __init__(
        self,
        *,
        min_total_ms: float = 0.0,
        clock: Callable[[], int] = time.perf_counter_ns,
    ) -> None:
        self.min_total_ms = max(0.0, float(min_total_ms))
        self._clock = clock
        self._stats: dict[str, _PoolStats] = {}

    def begin_pool(self, pool: str, order_count: int) -> object:
        return {"pool": pool, "order_count": int(order_count), "stage_ns": {}}

    def begin_stage(self, token: object, name: str) -> object:
        del token, name
        return self._clock()

    def end_stage(self, token: object, name: str, stage_token: object) -> None:
        elapsed = self._clock() - int(stage_token)
        stages = token["stage_ns"]  # type: ignore[index]
        stages[name] = stages.get(name, 0) + elapsed

    def record_projection(self, token: object) -> None:
        token["projection_calls"] = token.get("projection_calls", 0) + 1  # type: ignore[union-attr]

    def end_pool(self, token: object, **details: Any) -> None:
        pool = str(token["pool"])  # type: ignore[index]
        stats = self._stats.setdefault(pool, _PoolStats())
        stats.checks += 1
        order_count = int(token["order_count"])  # type: ignore[index]
        stats.orders_seen += order_count
        over_limit = bool(details.get("over_limit", False))
        if over_limit:
            stats.over_limit_checks += 1
            stats.over_limit_orders += order_count
        stats.scaled_orders += int(details.get("scaled_orders", 0) or 0)
        stats.projection_calls += int(token.get("projection_calls", 0))  # type: ignore[union-attr]
        scale = float(details.get("scale", 1.0))
        stats.scale_total += scale
        stats.scale_min = min(stats.scale_min, scale)
        stats.scale_max = max(stats.scale_max, scale)
        stats.full_utilization = float(details.get("full_utilization", 0.0))
        stats.final_utilization = float(details.get("final_utilization", 0.0))
        stats.maximum = float(details.get("maximum", 0.0))
        for name, elapsed in token["stage_ns"].items():  # type: ignore[index]
            stats.stage_ns[name] += int(elapsed)
            stats.stage_calls[name] += 1

    def flush(self, state: Any) -> None:
        from tools.testers.backtest.modules.runtime_info import record_runtime_info

        for pool, stats in self._stats.items():
            total_ms = sum(stats.stage_ns.values()) / 1_000_000.0
            if total_ms < self.min_total_ms:
                continue
            checks = stats.checks or 1
            orders = stats.orders_seen or 1
            over_limit_order_ratio = stats.over_limit_orders / orders
            scaled_order_ratio = stats.scaled_orders / orders
            details = {
                "cash_pool_id": pool,
                "checks": stats.checks,
                "orders_seen": stats.orders_seen,
                "over_limit_checks": stats.over_limit_checks,
                "over_limit_orders": stats.over_limit_orders,
                "scaled_orders": stats.scaled_orders,
                "over_limit_check_ratio": stats.over_limit_checks / checks,
                "over_limit_order_ratio": over_limit_order_ratio,
                "scaled_order_ratio": scaled_order_ratio,
                "projection_calls": stats.projection_calls,
                "mean_scale": stats.scale_total / checks,
                "min_scale": stats.scale_min,
                "max_scale": stats.scale_max,
                "last_full_utilization": stats.full_utilization,
                "last_final_utilization": stats.final_utilization,
                "max_utilization": stats.maximum,
                "stage_ms": {
                    name: round(value / 1_000_000.0, 3)
                    for name, value in stats.stage_ns.items()
                },
                "stage_calls": dict(stats.stage_calls),
            }
            record_runtime_info(
                state,
                code="backtest_margin_execution_profile",
                type="性能",
                status="profiled",
                level="info",
                message=(
                    f"保证金检查池 {pool}：{over_limit_order_ratio:.1%} 的订单处于超限检查，"
                    f"{scaled_order_ratio:.1%} 实际被缩放"
                ),
                detail=(
                    f"累计检查 {stats.checks} 次、订单 {stats.orders_seen} 个，"
                    f"组合投影 {stats.projection_calls} 次；阶段耗时 {total_ms:.1f}ms。"
                ),
                details=details,
                aggregation_key=f"margin_execution|{pool}",
            )

    def reset(self) -> None:
        self._stats.clear()


def normalize_margin_execution_profile(value: Any) -> dict[str, Any] | None:
    if value is None or value is False:
        return None
    if value is True:
        value = {}
    if not isinstance(value, dict):
        raise ValueError("margin_execution_profile must be an object")
    kind = str(value.get("kind") or "cumulative").strip()
    if kind != "cumulative":
        raise ValueError("margin_execution_profile.kind must be cumulative")
    minimum = float(value.get("min_total_ms", 0.0))
    if minimum < 0:
        raise ValueError("margin_execution_profile.min_total_ms must be non-negative")
    return {"kind": kind, "min_total_ms": minimum}


def build_margin_execution_observer(value: Any) -> MarginExecutionObserver | None:
    normalized = normalize_margin_execution_profile(value)
    if normalized is None:
        return None
    return CumulativeMarginExecutionObserver(min_total_ms=normalized["min_total_ms"])
