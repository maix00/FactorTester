import pandas as pd
from tools.data.types import DataFreq
from tools.factors import window_bars
from tools.factors.expr import CLOSE
from tools.factors.expr.streaming.calendar_window import TradingCalendarWindow, TradingSession
from tools.factors.expr.streaming.incremental import compile_incremental_factor


def test_session_sum_expands_and_evicts_in_o1_state():
    calendar = TradingCalendarWindow((
        TradingSession("2025-02-03", 0, 100, 2),
        TradingSession("2025-02-04", 1000, 1100, 3),
        TradingSession("2025-02-05", 2000, 2100, 1),
    ))
    executor = compile_incremental_factor("sum", CLOSE.rolling(window_bars("2d")).sum(),
        ("A",), source_freq=DataFreq.MIN1, session_calendar=calendar)
    assert executor._multi.uses_rust
    actual = []
    for value, stamp in enumerate([10, 20, 1010, 1020, 1030, 2010], 1):
        timestamp = pd.Timestamp(stamp, unit="ns")
        executor.on_bar(timestamp, {"A": {"CLOSE_ADJUSTED": value}})
        actual.append(executor.on_signal(timestamp)["A"])
    assert actual == [1, 3, 6, 10, 15, 18]  # day 1 evicted at day 3


def test_resolved_duration_quantile_preserves_q_and_day_scope():
    import numpy as np
    from tools.factors.expr import scope_trading_day
    calendar=TradingCalendarWindow((TradingSession('2025-02-03',0,100,2),
        TradingSession('2025-02-04',1000,1100,3),TradingSession('2025-02-05',2000,2100,1)))
    expressions=[CLOSE.rolling(pd.Timedelta(days=2)).quantile(.8),
                 CLOSE.groupby_scope(scope_trading_day()).quantile(.25)]
    expected=[[1,1.8,2.6,3.4,4.2,5.4],[1,1.25,3,3.25,3.5,6]]
    for expression,want in zip(expressions,expected):
        executor=compile_incremental_factor('quantile',expression,('A',),source_freq=DataFreq.MIN1,session_calendar=calendar)
        actual=[]
        for value,stamp in enumerate([10,20,1010,1020,1030,2010],1):
            time=pd.Timestamp(stamp,unit='ns');executor.on_bar(time,{'A':{'CLOSE_ADJUSTED':value}})
            actual.append(executor.on_signal(time)['A'])
        np.testing.assert_allclose(actual,want,rtol=0,atol=1e-12)
