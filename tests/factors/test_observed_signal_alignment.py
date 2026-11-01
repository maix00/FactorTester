"""The legacy DSL's observed-bar sampling must agree across Rust entrances."""
import json

import numpy as np
import pandas as pd

from alpha import FactorPlanState
from tools.data.types import DataColumn, DataFreq, finest_index
from tools.factors.alpha_plan import alpha_plan_spec
from tools.factors.expr import EvaluateContext, SignalAlign
from tools.factors.expr.leaf import ColumnRef


def test_batch_and_incremental_use_same_bar_ordinal_across_missing_bars():
    index = pd.DatetimeIndex(['2026-01-01 09:01', '2026-01-01 09:02',
                              '2026-01-01 09:04', '2026-01-01 09:05'], name='MIN1')
    prices = np.array([1., 2., 3., 4.])
    price = ColumnRef(DataColumn.CLOSE)
    expr = SignalAlign(price, '2m')
    ctx = EvaluateContext(products=['A'], freq=DataFreq.MIN1, cache={},
        preloaded={('A', DataFreq.MIN1.name): pd.DataFrame({'CLOSE': prices}, index=index)})
    batch = expr.evaluate(ctx=ctx)
    np.testing.assert_equal(batch['A'].to_numpy(), [2., 4.])
    spec = alpha_plan_spec(expr, source_freq=DataFreq.MIN1, products=('A',))
    assert spec['nodes'][-1]['observed_period'] == 2
    state = FactorPlanState(json.dumps({key: value for key, value in spec.items() if key != 'key_tuples'}), 1)
    incremental = [state.update_at(time.value, np.array([value]))[0] for time, value in zip(index, prices)]
    np.testing.assert_equal(incremental, [np.nan, 2., 2., 4.])
    positions = index.get_indexer(finest_index(batch.index))
    np.testing.assert_equal(np.asarray(incremental)[positions], batch['A'].to_numpy())
