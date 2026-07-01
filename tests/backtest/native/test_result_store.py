from __future__ import annotations

from tools.testers.backtest.engines.native.result_store import ResultStore
from tools.testers.backtest.engines.native.strategy import Strategy


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
