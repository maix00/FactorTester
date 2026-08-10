from __future__ import annotations

import pandas as pd
import pytest

from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.config import StrategyConfig
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.modules.equity_curve import (
    EquityCurveModule, _flush_equity_post_replay, _record_equity,
    display_equity_curve_for, equity_curve_for, position_curve_for,
)
from tools.testers.backtest.modules.ledger_module import LedgerModule


def _drive(account, points, live_equity):
    for ts, equity in points:
        ctx = FlowContext(timestamp=ts, event_queue=EventQueue(), active_strategies=frozenset(account.strategy_configs))
        for strategy in account.strategy_configs:
            ctx.set_for(LedgerModule.equity, strategy, equity)
        _record_equity(account, ctx)
    if not live_equity:
        post_ctx = FlowContext(timestamp=None, event_queue=EventQueue())
        _flush_equity_post_replay(account, post_ctx)


def test_live_and_post_produce_identical_final_curve():
    s_live = Strategy(alias="Live")
    s_post = Strategy(alias="Post")
    configs = {
        s_live: StrategyConfig(strategy=s_live, field_values={EquityCurveModule.equity_compute_live: True}),
        s_post: StrategyConfig(strategy=s_post, field_values={EquityCurveModule.equity_compute_live: False}),
    }
    points = [(pd.Timestamp("2024-01-01"), 1000.0), (pd.Timestamp("2024-01-02"), 1100.0),
              (pd.Timestamp("2024-01-03"), 1050.0)]

    account_live = BacktestRunState(strategy_configs={s_live: configs[s_live]})
    _drive(account_live, points, live_equity=True)
    curve_live = equity_curve_for(account_live, s_live)

    account_post = BacktestRunState(strategy_configs={s_post: configs[s_post]})
    _drive(account_post, points, live_equity=False)
    curve_post = equity_curve_for(account_post, s_post)

    pd.testing.assert_series_equal(curve_live, curve_post, check_names=False)


def test_live_mode_streams_during_run_before_post_replay():
    s = Strategy(alias="S")
    config = StrategyConfig(strategy=s, field_values={EquityCurveModule.equity_compute_live: True})
    account = BacktestRunState(strategy_configs={s: config})
    ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set_for(LedgerModule.equity, s, 500.0)
    _record_equity(account, ctx)
    # already in ResultStore, without ever calling _flush_equity_post_replay
    assert account.results.history(s) == [(pd.Timestamp("2024-01-01"), {"equity": 500.0})]
    assert account.equity_curve_store.buffer == {}


def test_post_mode_does_not_stream_until_flush():
    s = Strategy(alias="S")
    config = StrategyConfig(strategy=s, field_values={EquityCurveModule.equity_compute_live: False})
    account = BacktestRunState(strategy_configs={s: config})
    ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set_for(LedgerModule.equity, s, 500.0)
    _record_equity(account, ctx)
    assert account.results.history(s) == []  # not yet flushed
    assert account.equity_curve_store.buffer[s] == [
        (pd.Timestamp("2024-01-01"), {"equity": 500.0})
    ]


def test_display_equity_curve_keeps_only_signal_valuation_points():
    s = Strategy(alias="S")
    account = BacktestRunState(strategy_configs={s: StrategyConfig(strategy=s)})
    signal_ts = pd.Timestamp("2026-01-02 09:00:00", tz="Asia/Shanghai")
    order_ts = signal_ts + pd.Timedelta(microseconds=1)

    signal_ctx = FlowContext(
        timestamp=signal_ts,
        event_queue=EventQueue(),
        active_strategies=frozenset({s}),
        event_kind=EventKind.SIGNAL,
    )
    signal_ctx.set_for(LedgerModule.equity, s, 1000.0)
    _record_equity(account, signal_ctx)

    order_ctx = FlowContext(
        timestamp=order_ts,
        event_queue=EventQueue(),
        active_strategies=frozenset({s}),
        event_kind=EventKind.ORDER,
    )
    order_ctx.set_for(LedgerModule.equity, s, 990.0)
    _record_equity(account, order_ctx)

    full = equity_curve_for(account, s)
    display = display_equity_curve_for(account, s)

    assert list(full.index) == [signal_ts, order_ts]
    assert list(full.to_numpy()) == [1000.0, 990.0]
    assert list(display.index) == [signal_ts]
    assert list(display.to_numpy()) == [1000.0]


def test_summary_retention_uses_signal_display_buffer_for_curve():
    s = Strategy(alias="S")
    account = BacktestRunState(
        strategy_configs={s: StrategyConfig(strategy=s)},
        result_retention_mode="summary",
    )
    signal_ts = pd.Timestamp("2026-01-02 09:00:00", tz="Asia/Shanghai")
    signal_ctx = FlowContext(
        timestamp=signal_ts,
        event_queue=EventQueue(),
        active_strategies=frozenset({s}),
        event_kind=EventKind.SIGNAL,
    )
    signal_ctx.set_for(LedgerModule.equity, s, 1000.0)
    _record_equity(account, signal_ctx)
    order_ctx = FlowContext(
        timestamp=signal_ts + pd.Timedelta(microseconds=1),
        event_queue=EventQueue(),
        active_strategies=frozenset({s}),
        event_kind=EventKind.ORDER,
    )
    order_ctx.set_for(LedgerModule.equity, s, 990.0)
    _record_equity(account, order_ctx)

    assert list(equity_curve_for(account, s).to_numpy()) == [1000.0]
    assert position_curve_for(account, s) == {}
