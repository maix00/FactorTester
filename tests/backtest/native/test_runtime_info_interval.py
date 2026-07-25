from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pandas as pd

from tools.testers.backtest.engines.native.config import StrategyConfig
from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowRegistry, run
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.runtime_info import record_runtime_fallback_interval


def test_runtime_fallback_interval_keeps_constant_size_monotonic_state():
    state = SimpleNamespace(runtime_info_rows=[], runtime_info_sink=None)

    for timestamp in (
        "2024-01-02 09:01:00",
        "2024-01-02 09:01:00",
        "2024-01-02 09:02:00",
    ):
        record_runtime_fallback_interval(
            state,
            code="test_fallback",
            type="测试",
            status="已降级",
            product="AP.CZC",
            timestamp=timestamp,
            source="source",
            fallback="fallback",
            reason="test",
        )

    details = state.runtime_info_rows[0]["details"]
    assert details["start"] == "2024-01-02 09:01:00"
    assert details["end"] == "2024-01-02 09:02:00"
    assert details["count"] == 2
    assert details["last_timestamp"] == "2024-01-02 09:02:00"
    assert "_seen_timestamps" not in details


def test_runtime_fallback_interval_migrates_legacy_timestamp_history():
    state = SimpleNamespace(
        runtime_info_rows=[{
            "code": "test_fallback",
            "aggregation_key": "AP.CZC|source->fallback",
            "details": {
                "start": "2024-01-02 09:01:00",
                "end": "2024-01-02 09:02:00",
                "count": 2,
                "_seen_timestamps": [
                    "2024-01-02 09:01:00",
                    "2024-01-02 09:02:00",
                ],
            },
        }],
        runtime_info_sink=None,
    )

    record_runtime_fallback_interval(
        state,
        code="test_fallback",
        type="测试",
        status="已降级",
        product="AP.CZC",
        timestamp="2024-01-02 09:03:00",
        source="source",
        fallback="fallback",
        reason="test",
    )

    details = state.runtime_info_rows[0]["details"]
    assert details["start"] == "2024-01-02 09:01:00"
    assert details["end"] == "2024-01-02 09:03:00"
    assert details["count"] == 3
    assert details["last_timestamp"] == "2024-01-02 09:03:00"
    assert "_seen_timestamps" not in details


def test_runtime_fallback_interval_cost_and_details_stay_bounded():
    state = SimpleNamespace(runtime_info_rows=[], runtime_info_sink=None)
    kwargs = {
        "code": "test_fallback",
        "type": "测试",
        "status": "已降级",
        "product": "AP.CZC",
        "source": "source",
        "fallback": "fallback",
        "reason": "test",
    }
    record_runtime_fallback_interval(state, timestamp="2024-00000000", **kwargs)
    initial_size = len(json.dumps(state.runtime_info_rows[0]["details"]))

    started_at = time.perf_counter()
    for index in range(1, 10_001):
        record_runtime_fallback_interval(
            state, timestamp=f"2024-{index:08d}", **kwargs,
        )
    elapsed = time.perf_counter() - started_at

    details = state.runtime_info_rows[0]["details"]
    assert details["count"] == 10_001
    assert len(json.dumps(details)) <= initial_size + 16
    assert elapsed < 2.5


def test_event_replay_slice_records_one_bounded_monotonic_interval():
    strategy = Strategy(alias="slice")
    flow = Flow(
        "record_slice_fallback",
        inputs=(),
        outputs=(),
        phase=Phase.PER_EVENT,
        event_kind=EventKind.SIGNAL,
        compute=lambda state, ctx: record_runtime_fallback_interval(
            state,
            code="slice_fallback",
            type="测试",
            status="已降级",
            product="AP.CZC",
            timestamp=ctx.timestamp,
            source="source",
            fallback="fallback",
            reason="test",
        ),
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    state = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            active_flow_names=frozenset({flow.name}),
        ),
    })
    timestamps = pd.date_range("2024-01-02 09:01:00", periods=240, freq="min")
    queue = EventQueue()
    queue.push_events([
        EventDraft(EventKind.SIGNAL, timestamp, strategy)
        for timestamp in reversed(timestamps)
    ])

    run(state, queue, registry.resolve())

    details = state.runtime_info_rows[0]["details"]
    assert details["start"] == str(timestamps[0])
    assert details["end"] == str(timestamps[-1])
    assert details["last_timestamp"] == str(timestamps[-1])
    assert details["count"] == len(timestamps)
    assert "_seen_timestamps" not in details
