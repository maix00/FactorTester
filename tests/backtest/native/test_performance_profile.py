from __future__ import annotations

import pytest

from tools.testers.backtest.engines.native.performance_profile import (
    build_backtest_profiler,
    normalize_performance_profile,
)
from tools.testers.backtest.engines.native.profiling import (
    CumulativeBacktestProfiler,
)
from tools.testers.backtest.modules.margin_budget_impl.observability import (
    CumulativeMarginExecutionObserver,
    build_margin_execution_observer,
    normalize_margin_execution_profile,
)


def test_performance_profile_is_opt_in() -> None:
    assert normalize_performance_profile(None) is None
    assert build_backtest_profiler(None) is None


def test_cumulative_flow_profile_builds_pluggable_profiler() -> None:
    value = normalize_performance_profile({
        "kind": "cumulative_flow",
        "min_total_ms": 125.5,
    })

    assert value == {
        "kind": "cumulative_flow",
        "min_total_ms": 125.5,
    }
    profiler = build_backtest_profiler(value)
    assert isinstance(profiler, CumulativeBacktestProfiler)
    assert profiler.min_duration_ms == 125.5


def test_margin_execution_profile_is_opt_in_and_pluggable() -> None:
    assert normalize_margin_execution_profile(None) is None
    value = normalize_margin_execution_profile({"min_total_ms": 15})
    assert value == {"kind": "cumulative", "min_total_ms": 15.0}
    observer = build_margin_execution_observer(value)
    assert isinstance(observer, CumulativeMarginExecutionObserver)
    assert observer.min_total_ms == 15.0


@pytest.mark.parametrize(
    "value",
    [
        True,
        {},
        {"kind": "unknown"},
        {"kind": "cumulative_flow", "min_total_ms": -1},
    ],
)
def test_invalid_performance_profile_is_rejected(value) -> None:
    with pytest.raises(ValueError):
        normalize_performance_profile(value)


@pytest.mark.parametrize("value", [{"kind": "unknown"}, {"min_total_ms": -1}])
def test_invalid_margin_execution_profile_is_rejected(value) -> None:
    with pytest.raises(ValueError):
        normalize_margin_execution_profile(value)
