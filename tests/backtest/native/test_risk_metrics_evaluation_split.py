from __future__ import annotations

import pandas as pd
import pytest

from tools.testers.backtest.engines.native.ledger import AccountState, StrategyConfig
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.risk_metrics import RiskMetricsModule, _compute_risk_metrics
from tools.testers.backtest.modules.run_window import RunWindowModule


def _seed_equity(account, strategy, points):
    for ts, equity in points:
        account.results.append(strategy, ts, equity=equity)


def test_no_split_reports_only_in_sample_metrics():
    s = Strategy(alias="S")
    config = StrategyConfig(strategy=s)
    account = AccountState(strategy_configs={s: config})
    idx = pd.date_range("2024-01-01", periods=5)
    _seed_equity(account, s, [(t, 100.0 + i) for i, t in enumerate(idx)])

    _compute_risk_metrics(account, FlowContext(timestamp=None, event_queue=EventQueue()))
    final = account.results.get_final(s)
    assert "sharpe_ratio" in final
    assert not any(k.startswith("out_of_sample_") for k in final)


def test_split_separates_in_and_out_of_sample_metrics():
    s = Strategy(alias="S")
    idx = pd.date_range("2024-01-01", periods=10)
    config = StrategyConfig(strategy=s, field_values={
        RunWindowModule.evaluation_split: idx[4],  # first 5 points in-sample
    })
    account = AccountState(strategy_configs={s: config})
    # in-sample: flat (no volatility); out-of-sample: trending up
    equity_values = [100.0] * 5 + [100.0 + i * 5 for i in range(1, 6)]
    _seed_equity(account, s, list(zip(idx, equity_values)))

    _compute_risk_metrics(account, FlowContext(timestamp=None, event_queue=EventQueue()))
    final = account.results.get_final(s)

    assert final["max_drawdown"] == pytest.approx(0.0)  # in-sample segment is flat
    assert "out_of_sample_max_drawdown" in final
    assert final["out_of_sample_win_rate"] > final["win_rate"]  # out-of-sample trends up, in-sample flat
