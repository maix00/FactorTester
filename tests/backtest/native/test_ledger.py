from __future__ import annotations

import dataclasses
import warnings

import pandas as pd
import pytest

from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.config import StrategyConfig
from tools.testers.backtest.engines.native.ledger import LedgerState
from tools.testers.backtest.engines.native.order import Order
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.base import FieldRef


def test_ledger_get_set_roundtrip():
    s = Strategy(alias="A")
    ledger = LedgerState(strategy=s, base_currency="CNY")
    ref = FieldRef("cash", owner="LedgerModule")
    assert ledger.get(ref, "default") == "default"
    ledger.set(ref, 100.0)
    assert ledger.get(ref) == 100.0


def test_ledger_has_no_named_business_fields():
    names = {f.name for f in dataclasses.fields(LedgerState)}
    assert names == {"strategy", "base_currency", "ledger", "fields"}


def test_run_state_ledger_for_isolates_strategies():
    s1 = Strategy(alias="S1")
    s2 = Strategy(alias="S2")
    l1 = LedgerState(strategy=s1, base_currency="CNY", ledger_id="private:S1")
    l2 = LedgerState(strategy=s2, base_currency="CNY", ledger_id="private:S2")
    account = BacktestRunState(
        ledgers={"private:S1": l1, "private:S2": l2},
        strategy_configs={s1: StrategyConfig(strategy=s1), s2: StrategyConfig(strategy=s2)},
    )

    o1 = Order(instrument="P1", timestamp=pd.Timestamp("2024-01-01"),
               quantity=1.0, intent_quantity=1.0, strategy=s1)
    o2 = Order(instrument="P1", timestamp=pd.Timestamp("2024-01-01"),
               quantity=1.0, intent_quantity=1.0, strategy=s2)

    assert account.ledger_for(o1) is l1
    assert account.ledger_for(o2) is l2

    ref = FieldRef("cash", owner="LedgerModule")
    l1.set(ref, 1.0)
    assert l2.get(ref) is None


def test_run_state_dynamic_write_audit_is_off_by_default():
    state = BacktestRunState()
    state.some_module_cache = {"ok": True}
    assert state.some_module_cache == {"ok": True}


def test_run_state_dynamic_write_audit_warns_for_unknown_attrs():
    state = BacktestRunState()
    state.enable_dynamic_write_audit()
    with pytest.warns(RuntimeWarning, match="some_module_cache"):
        state.some_module_cache = {"ok": True}
    with warnings.catch_warnings(record=True) as records:
        state.some_module_cache = {"ok": False}
    assert len(records) == 0


def test_run_state_dynamic_write_audit_allows_declared_attrs():
    state = BacktestRunState()
    state.enable_dynamic_write_audit()
    with warnings.catch_warnings(record=True) as records:
        state.market_data_request = {"start_dt": "2026-01-01"}
    assert len(records) == 0
