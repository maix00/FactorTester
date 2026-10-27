"""Independent causal/scope oracle; production must not use Python search math."""
import json
import numpy as np
import pandas as pd
from alpha import FactorPlanState
from tools.data.types import DataFreq
from tools.factors.expr import CURRENT,CANDIDATE,scope_bars,scope_trading_day,SignalAlign,EvaluateContext
from tools.factors.expr.conditional import where
from tools.factors.expr.timeline import PanelTimeline
from tools.factors.alpha_plan import alpha_plan_spec
from tools.factors.FactorExpr import CLOSE_RAW
from tests.factors.test_bar_search import _FrameExpr


def ctx(index,days=None):
    timeline=PanelTimeline(index=index,products=('A',),trading_days=pd.Index(index.normalize() if days is None else days),
        observed_mask=pd.DataFrame(True,index=index,columns=['A']),same_session=True)
    return EvaluateContext(products=('A',),freq=DataFreq.MIN1,cache={},panel_timeline=timeline)


def test_partition_barrier_is_not_a_sliding_lookback():
    index=pd.date_range('2026-01-01',periods=6,freq='min',name='MIN1')
    value=_FrameExpr(pd.DataFrame({'A':range(6)},index=index))
    partition=value.bar_distance(CANDIDATE<CURRENT,scope=scope_bars(3),default=9).evaluate(ctx=ctx(index))
    sliding=value.bar_distance(CANDIDATE<CURRENT,lookback=3,default=9).evaluate(ctx=ctx(index))
    np.testing.assert_equal(partition['A'].to_numpy(),[9,1,1,9,1,1])
    np.testing.assert_equal(sliding['A'].to_numpy(),[9,1,1,1,1,1])


def test_night_belongs_to_frozen_trading_day_and_lookback_stays_inside_scope():
    index=pd.to_datetime(['2026-01-01 14:59','2026-01-01 21:01','2026-01-02 09:01','2026-01-02 09:02'])
    days=pd.to_datetime(['2026-01-01','2026-01-02','2026-01-02','2026-01-02'])
    value=_FrameExpr(pd.DataFrame({'A':range(4)},index=index))
    whole=value.bar_distance(CANDIDATE<CURRENT,scope=scope_trading_day(),select='farthest',default=9).evaluate(ctx=ctx(index,days))
    limited=value.bar_distance(CANDIDATE<CURRENT,scope=scope_trading_day(),lookback=1,select='farthest',default=9).evaluate(ctx=ctx(index,days))
    np.testing.assert_equal(whole['A'].to_numpy(),[9,9,1,2])
    np.testing.assert_equal(limited['A'].to_numpy(),[9,9,1,1])


def test_where_with_nested_signal_matches_every_prefix_and_incremental_core():
    from tools.factors.expr.leaf import ColumnRef
    from tools.data.types import DataColumn
    index=pd.date_range('2026-01-01 09:01',periods=12,freq='min',name='MIN1')
    prices=np.array([1,2,5,3,8,7,9,2,4,12,1,15.],dtype=float)
    # Keep a real shared source column so the same expression serializes to the native bridge.
    price=ColumnRef(DataColumn.CLOSE)
    formed=SignalAlign(price.rolling(2).mean(),'3m')
    predicate=where(CURRENT>CANDIDATE,(CURRENT-CANDIDATE)>formed/10,False)
    expression=price.bar_distance(predicate,scope=scope_bars(5),lookback=3,default=9)
    expected=[]
    for i,current in enumerate(prices):
        target=((i+1)//3)*3-1
        threshold=np.mean(prices[max(0,target-1):target+1])/10 if target>=0 else np.nan
        found=[i-j for j in range(max((i//5)*5,i-3),i) if current>prices[j] and current-prices[j]>threshold]
        expected.append(min(found) if found else 9)
    spec=alpha_plan_spec(expression,source_freq=DataFreq.MIN1,products=('A',))
    assert spec['nodes'][-1]['kind']=='search' and len(spec['nodes'][-1]['dependencies'])==1
    for end in range(1,len(prices)+1):
        context=ctx(index[:end])._replace(preloaded={('A',DataFreq.MIN1.name):pd.DataFrame({'CLOSE':prices[:end]},index=index[:end])})
        actual=expression.evaluate(ctx=context)['A'].to_numpy()
        np.testing.assert_allclose(actual,expected[:end])
        state=FactorPlanState(json.dumps({k:v for k,v in spec.items() if k!='key_tuples'}),1)
        for t,value,want in zip(index[:end],prices[:end],expected):
            np.testing.assert_equal(state.update_at(t.value,np.array([value]))[0],want)
