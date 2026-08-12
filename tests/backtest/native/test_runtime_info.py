from __future__ import annotations

from typing import Any

from tools.testers.backtest.modules.runtime_info import record_runtime_fallback_interval
from tools.testers.backtest.engines.native.profiling import CumulativeBacktestProfiler


class _State:
    def __init__(self) -> None:
        self.runtime_info_rows: list[dict[str, Any]] = []
        self.runtime_info_sink = _Sink()


class _Sink:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def emit_runtime_info(self, message: str, **kwargs: Any) -> None:
        self.events.append({"message": message, **kwargs})


class _Product:
    name = "RU.SHF"
    desc = "橡胶"


def test_runtime_fallback_interval_reuses_index_and_respects_external_appends():
    state = _State()
    product = _Product()

    record_runtime_fallback_interval(
        state,
        code="price_fallback",
        type="行情",
        status="回退",
        product=product,
        timestamp="2026-01-05 09:01:00",
        source="settlement",
        fallback="close",
        reason="缺少结算价",
    )
    record_runtime_fallback_interval(
        state,
        code="price_fallback",
        type="行情",
        status="回退",
        product=product,
        timestamp="2026-01-05 09:02:00",
        source="settlement",
        fallback="close",
        reason="缺少结算价",
    )

    assert len(state.runtime_info_rows) == 1
    assert state.runtime_info_rows[0]["details"]["count"] == 2
    assert len(state.runtime_info_sink.events) == 1

    record_runtime_fallback_interval(
        state,
        code="price_fallback",
        type="行情",
        status="回退",
        product=product,
        timestamp="2026-01-05 09:02:00",
        source="settlement",
        fallback="close",
        reason="缺少结算价",
    )

    assert len(state.runtime_info_rows) == 1
    assert state.runtime_info_rows[0]["details"]["count"] == 2
    assert len(state.runtime_info_sink.events) == 1

    state.runtime_info_rows.append(
        {
            "code": "price_fallback",
            "aggregation_key": "RU.SHF|settlement->close|scope=external",
            "details": {"start": "2026-01-05 09:03:00", "end": "2026-01-05 09:03:00", "count": 1},
        }
    )

    record_runtime_fallback_interval(
        state,
        code="price_fallback",
        type="行情",
        status="回退",
        product=product,
        timestamp="2026-01-05 09:04:00",
        source="settlement",
        fallback="close",
        reason="缺少结算价",
        extra={"scope": "external"},
    )

    assert len(state.runtime_info_rows) == 2
    assert state.runtime_info_rows[1]["details"]["count"] == 2
    assert state.runtime_info_rows[1]["details"]["end"] == "2026-01-05 09:04:00"
    assert len(state.runtime_info_sink.events) == 1


def test_result_assembly_profile_records_runtime_info_row():
    state = _State()
    clock = iter((0.0, 0.0125))
    profiler = CumulativeBacktestProfiler(min_duration_ms=0.0, clock=lambda: next(clock))
    token = profiler.begin_stage("result_assembly")

    profiler.end_stage(
        token,
        state,
        name="result_assembly",
        details={"strategy_count": 2, "portfolio_count": 2},
    )

    assert len(state.runtime_info_rows) == 1
    assert state.runtime_info_rows[0]["code"] == "backtest_result_assembly_profile"
    assert state.runtime_info_rows[0]["details"]["phase"] == "result_assembly"
    assert state.runtime_info_rows[0]["details"]["elapsed_ms"] == 12.5
