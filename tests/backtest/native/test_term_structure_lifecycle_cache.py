from __future__ import annotations

import pandas as pd

from tools.data.types.time_index import DataIndex
from tools.testers.backtest.engines.native.config import StrategyConfig
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules import term_structure
from tools.testers.backtest.modules.run_window import RunWindowModule


def test_date_only_lifecycle_anchors_reuse_the_loaded_market_axis(monkeypatch):
    strategy = Strategy(alias="A")
    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            field_values={
                RunWindowModule.timezone: "Asia/Shanghai",
                RunWindowModule.time_precision: "exact",
            },
        ),
    })
    account.market_data_store.current_prices_table = pd.DataFrame(
        {"P2601.DCE": [10.0, 11.0]},
        index=pd.DatetimeIndex([
            pd.Timestamp("2026-01-31 09:01", tz="Asia/Shanghai"),
            pd.Timestamp("2026-01-31 15:00", tz="Asia/Shanghai"),
        ]),
    )
    rows = [
        {"uid": f"P260{number}.DCE", "last_trade_date": "2026-01-31"}
        for number in (1, 2)
    ]
    original = DataIndex.trading_day_last_event_times_from_index
    calls = 0

    def counted(index):
        nonlocal calls
        calls += 1
        return original(index)

    monkeypatch.setattr(
        DataIndex,
        "trading_day_last_event_times_from_index",
        staticmethod(counted),
    )

    timestamps = [
        term_structure._event_timestamp_from_row(
            row,
            offset=pd.Timedelta(0),
            state=account,
            reference_tz="Asia/Shanghai",
            peer_rows=rows,
            engine_mode="auto",
            lifecycle_anchor="force_close",
        )
        for row in rows
    ]

    expected = pd.Timestamp("2026-01-31 15:00", tz="Asia/Shanghai")
    assert timestamps == [expected, expected]
    assert calls == 1
