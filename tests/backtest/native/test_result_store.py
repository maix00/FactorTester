from __future__ import annotations

from tools.testers.backtest.engines.native.result_store import ResultStore
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.modules.target import TargetStore
from tools.factors.tester_calc.single_factor_test.group.research_run.projection import _trace_checksum
import pandas as pd


def test_append_and_history_roundtrip():
    store = ResultStore()
    s = Strategy(alias="S")
    store.append(s, "t1", equity=100.0)
    store.append(s, "t2", equity=110.0)
    history = store.history(s)
    assert history == [("t1", {"equity": 100.0}), ("t2", {"equity": 110.0})]


def test_history_isolated_per_strategy():
    store = ResultStore()
    s1, s2 = Strategy(alias="A"), Strategy(alias="B")
    store.append(s1, "t1", equity=100.0)
    assert store.history(s2) == []


def test_set_final_and_get_final():
    store = ResultStore()
    s = Strategy(alias="S")
    store.set_final(s, sharpe_ratio=1.5)
    store.set_final(s, max_drawdown=-0.1)
    assert store.get_final(s) == {"sharpe_ratio": 1.5, "max_drawdown": -0.1}


def test_get_final_missing_strategy_returns_empty_dict():
    store = ResultStore()
    s = Strategy(alias="S")
    assert store.get_final(s) == {}


def test_summary_retention_discards_intrabar_snapshots():
    store = ResultStore(retention_mode="summary")
    strategy = Strategy(alias="S")
    store.append(
        strategy,
        "signal",
        event_kind=EventKind.SIGNAL,
        equity=100.0,
        positions={"RB.SHF": 1.0},
        notional={"RB.SHF": 10_000.0},
    )
    store.append(
        strategy,
        "order",
        event_kind=EventKind.ORDER,
        equity=99.0,
        positions={"RB.SHF": 1.0},
        notional={"RB.SHF": 9_900.0},
    )
    assert store.history(strategy) == [("signal", {"equity": 100.0})]


def test_summary_target_trace_keeps_count_and_checksum_without_weights():
    timestamps = [
        pd.Timestamp("2024-01-01T09:00:00"),
        pd.Timestamp("2024-01-01T09:05:00"),
    ]
    weights = [{"RB.SHF": 0.5, "CU.SHF": -0.5}, {"RB.SHF": 0.25}]
    strategy = Strategy(alias="S")
    compact = TargetStore(retention_mode="summary")
    full = TargetStore(retention_mode="full")
    for timestamp, value in zip(timestamps, weights, strict=True):
        compact.record_target_trace(strategy, timestamp, value)
        full.record_target_trace(strategy, timestamp, value)
    compact_trace = compact.target_trace_for(strategy)
    full_trace = full.target_trace_for(strategy)
    assert len(compact_trace) == len(full_trace) == 2
    assert _trace_checksum(compact_trace) == _trace_checksum(full_trace)
    assert not hasattr(compact_trace, "target_trace")
