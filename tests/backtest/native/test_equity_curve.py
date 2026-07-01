from __future__ import annotations

import pandas as pd
import pytest

from tools.testers.backtest.engines.native.ledger import BacktestRunState, StrategyConfig
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.equity_curve import (
    EquityCurveModule, _flush_equity_post_replay, _record_equity, equity_curve_for,
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


def test_post_mode_does_not_stream_until_flush():
    s = Strategy(alias="S")
    config = StrategyConfig(strategy=s, field_values={EquityCurveModule.equity_compute_live: False})
    account = BacktestRunState(strategy_configs={s: config})
    ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set_for(LedgerModule.equity, s, 500.0)
    _record_equity(account, ctx)
    assert account.results.history(s) == []  # not yet flushed
