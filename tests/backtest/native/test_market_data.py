from __future__ import annotations

from typing import cast

import numpy as np
import pandas as pd

from tools.testers.backtest.engines.native.ledger import AccountState
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.modules.market_data import (
    MarketDataModule, _causal_valuation, _load_raw_market_data, current_prices_at,
)


def test_load_raw_market_data_reads_from_account_supplied_input():
    account = AccountState()
    raw_prices = pd.DataFrame({"P1": [1.0, 2.0]}, index=pd.date_range("2024-01-01", periods=2))
    account.raw_market_data = {"raw_prices": raw_prices, "lot_sizes": {"P1": 5.0}}
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    _load_raw_market_data(account, ctx)
    assert ctx.get(MarketDataModule.raw_prices) is raw_prices
    assert ctx.get(MarketDataModule.lot_sizes) == {"P1": 5.0}


def test_out_of_range_products_emit_one_runtime_info_row(monkeypatch):
    class _Freq:
        name = "min1"

    class _Product:
        def __init__(self, name: str):
            self.name = name
            self.desc = name
            self.min1 = self

        def list_available_freqs(self):
            return [_Freq()]

        def get_and_adjust_cols(self, *args, **kwargs):
            raise ValueError("outside")

    p1 = _Product("ER.CZC")
    p2 = _Product("ME.CZC")
    account = AccountState()
    account.market_data_request = {"products": [p1, p2]}
    setattr(account, "_market_data_load_plan", [(p1, _Freq()), (p2, _Freq())])
    account.runtime_info_rows = []
    monkeypatch.setattr(
        "tools.testers.backtest.modules.market_data._product_outside_run_window",
        lambda product, start_dt, end_dt: True,
    )
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())

    _load_raw_market_data(account, ctx)

    assert len(account.runtime_info_rows) == 1
    row = account.runtime_info_rows[0]
    assert row["code"] == "market_data_out_of_range_products_removed"
    assert row["details"]["product_names"] == ["ER.CZC", "ME.CZC"]
    assert "ER.CZC" in row["detail"] and "ME.CZC" in row["detail"]


def test_causal_valuation_ffills_gaps_and_never_looks_ahead():
    account = AccountState()
    idx = pd.date_range("2024-01-01", periods=4)
    raw_prices = pd.DataFrame({"P1": [10.0, np.nan, np.nan, 40.0]}, index=idx)
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set(MarketDataModule.raw_prices, raw_prices)
    _causal_valuation(account, ctx)

    # gap at idx[1]/idx[2] should be filled with the prior observed value (10.0),
    # not the future value (40.0) -- this is the no-lookahead guarantee
    assert current_prices_at(account, cast(pd.Timestamp, idx[1]))["P1"] == 10.0
    assert current_prices_at(account, cast(pd.Timestamp, idx[2]))["P1"] == 10.0
    assert current_prices_at(account, cast(pd.Timestamp, idx[3]))["P1"] == 40.0
    assert current_prices_at(account, cast(pd.Timestamp, idx[0]))["P1"] == 10.0
