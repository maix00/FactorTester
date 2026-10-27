"""Host integration for explicit alpha output collection, without new evaluators."""
from types import SimpleNamespace
import numpy as np
import pandas as pd

from tools.data.types import DataFreq, DataColumn
from tools.factors import FactorFamily
from tools.factors.expr import ColumnRef
from tools.factors.evaluation.batch import PreparedEvaluationBatch, evaluate_factors
from tools.factors.expr.timeline import build_panel_timeline


class _QueryFamily(FactorFamily):
    source_freq=DataFreq.MIN1
    signal_freq=DataFreq.MIN1
    @staticmethod
    def factor_expr():
        inner=ColumnRef(DataColumn.CLOSE).rolling(2).semantics(min_periods=1).mean().as_intermediate('mean')
        return inner+inner


class _Product:
    name='test-query'
    def list_available_freqs(self):return [DataFreq.MIN1]


def test_batch_queries_share_one_plan_and_are_opt_in(monkeypatch):
    import tools.factors.expr.rust_plan as compiler
    product=_Product()
    times=pd.date_range('2026-01-05 09:01',periods=4,freq='min')
    preloaded={(product,'MIN1'):pd.DataFrame({'CLOSE':[1.,3.,5.,7.]},index=times)}
    timeline=build_panel_timeline((product,),DataFreq.MIN1,preloaded)
    prepared=PreparedEvaluationBatch((product,),DataFreq.MIN1,times[0],times[-1],None,preloaded,timeline)
    factor=_QueryFamily().get_factor(**{'$F':'1m'})
    calls=[]
    original=compiler.evaluate_rust_plan
    def execute(expressions,context):
        calls.append(len(expressions))
        return original(expressions,context)
    monkeypatch.setattr(compiler,'evaluate_rust_plan',execute)
    context=evaluate_factors([factor],products=[product],freq=DataFreq.MIN1,
        start_dt=times[0],end_dt=times[-1],prepared=prepared,intermediates=('mean',))
    assert len(calls)==1
    value=factor.get_intermediate('mean')
    assert value is context.shared_cache[factor._intermediate_alias_index['mean']]
    np.testing.assert_allclose(value[product],[1.,2.,4.,6.])
    np.testing.assert_allclose(factor.table[product],[2.,4.,8.,12.])
    for _ in range(10):assert factor.get_intermediate('mean') is value
    assert len(calls)==1
    evaluate_factors([factor],products=[product],freq=DataFreq.MIN1,
        start_dt=times[0],end_dt=times[-1],prepared=prepared)
    assert factor.get_intermediate('mean') is None
    assert factor._intermediate_factor_data=={}
    factor.clear()
