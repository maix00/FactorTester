from __future__ import annotations

import dataclasses

import pandas as pd

from tools.testers.backtest.engines.native.ledger import RunState, Ledger
from tools.testers.backtest.engines.native.order import Order
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.base import FieldRef


def test_ledger_get_set_roundtrip():
    s = Strategy(alias="A")
    ledger = Ledger(strategy=s, base_currency="CNY")
    ref = FieldRef("cash", owner="LedgerModule")
    assert ledger.get(ref, "default") == "default"
    ledger.set(ref, 100.0)
    assert ledger.get(ref) == 100.0


def test_ledger_has_no_named_business_fields():
    names = {f.name for f in dataclasses.fields(Ledger)}
    assert names == {"strategy", "base_currency", "fields"}


def test_account_state_ledger_for_isolates_strategies():
    s1 = Strategy(alias="S1")
    s2 = Strategy(alias="S2")
    l1 = Ledger(strategy=s1, base_currency="CNY")
    l2 = Ledger(strategy=s2, base_currency="CNY")
    account = RunState(ledgers={s1: l1, s2: l2})

    o1 = Order(instrument="P1", timestamp=pd.Timestamp("2024-01-01"),
               quantity=1.0, intent_quantity=1.0, strategy=s1)
    o2 = Order(instrument="P1", timestamp=pd.Timestamp("2024-01-01"),
               quantity=1.0, intent_quantity=1.0, strategy=s2)

    assert account.ledger_for(o1) is l1
    assert account.ledger_for(o2) is l2

    ref = FieldRef("cash", owner="LedgerModule")
    l1.set(ref, 1.0)
    assert l2.get(ref) is None
