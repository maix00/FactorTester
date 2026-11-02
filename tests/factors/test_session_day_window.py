"""Trading-day windows use the actual trading calendar, not nominal bar counts."""
import numpy as np
import pandas as pd

from tools.data.types import DataColumn, DataFreq
from tools.factors.expr import EvaluateContext
from tools.factors.expr.leaf import ColumnRef

def test_day_window_uses_complete_trading_days_with_variable_bar_counts():
    from types import SimpleNamespace
    from tools.factors.expr.timeline import PanelTimeline

    class Product:
        MIN1 = SimpleNamespace(day_periods=2)
    product = Product()
    times = pd.to_datetime(['2026-01-05 09:01', '2026-01-05 09:02', '2026-01-05 09:03',
                            '2026-01-06 09:01', '2026-01-07 09:01', '2026-01-07 09:02'])
    days = pd.to_datetime(['2026-01-05'] * 3 + ['2026-01-06'] + ['2026-01-07'] * 2)
    index = pd.MultiIndex.from_arrays([days, times], names=['DAY1', 'MIN1'])
    frame = pd.DataFrame({'CLOSE': np.arange(1., 7.)}, index=index)
    timeline = PanelTimeline(index=index, products=(product,), trading_days=pd.Index(days),
                             observed_mask=pd.DataFrame(True, index=index, columns=[product]), same_session=True)
    ctx = EvaluateContext(products=[product], freq=DataFreq.MIN1, cache={}, panel_timeline=timeline,
                          preloaded={(product, DataFreq.MIN1.name): frame})
    result = ColumnRef(DataColumn.CLOSE).rolling('2d').sum().evaluate(ctx=ctx)
    np.testing.assert_equal(result[product].to_numpy(), [1., 3., 6., 10., 9., 15.])
