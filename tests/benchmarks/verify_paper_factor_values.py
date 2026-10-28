"""Opt-in math audit of stored paper families on explicit continuous-price data.

Not a strategy Job or a production reader. Pandas/NumPy form a test-only scalar
oracle. Rust is advanced through its diagnostic binding; no trading or profits
are claimed. Only explicitly requested output arrays are retained by this tool.
"""
from __future__ import annotations
import argparse,json,time
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from pandas.api.indexers import BaseIndexer


def oracle(times,days,price,adjusted):
    starts=np.r_[0,np.flatnonzero(days[1:]!=days[:-1])+1]
    ordinals=np.searchsorted(starts,np.arange(len(times)),side='right')-1
    def rolling(values,count,q):
        left=starts[np.maximum(0,ordinals-count+1)]
        class Bounds(BaseIndexer):
            def get_window_bounds(self,num_values=0,min_periods=None,center=None,closed=None,step=None):
                return left,np.arange(1,num_values+1,dtype=np.int64)
        result=pd.Series(values).rolling(Bounds(),min_periods=1).quantile(q).to_numpy(copy=True)
        invalid=np.r_[0,np.cumsum(np.isnan(values))]
        result[invalid[1:]-invalid[left]>0]=np.nan
        return result
    def signal(values):
        interval=1800000000000;target=times//interval*interval
        positions=np.searchsorted(times,target,side='right')-1
        valid=(positions>=0)&(target>=-(-int(times[0])//interval)*interval)
        out=np.full(len(times),np.nan);out[valid]=values[positions[valid]];return out
    difference=np.r_[np.nan,np.abs(adjusted[1:]-adjusted[:-1])]
    threshold=signal(rolling(difference,250,.6))
    duration=np.empty(len(times))
    for i in range(len(times)):
        start=starts[ordinals[i]]
        hits=np.flatnonzero(np.abs(adjusted[i]-adjusted[start:i])>=threshold[i])
        duration[i]=i-(start+hits[-1]) if len(hits) else i-start
    duration=signal(duration)
    series=pd.Series(duration)
    quantile=series.groupby(ordinals).expanding(min_periods=1).quantile(.9875).droplevel(0).sort_index().to_numpy(copy=True)
    nan_counts=series.isna().astype(int).groupby(ordinals).cumsum().to_numpy()
    quantile[nan_counts>0]=np.nan
    top=(duration>=quantile).astype(float)
    fair=pd.Series(price*top).groupby(ordinals).cumsum().to_numpy()/(pd.Series(top).groupby(ordinals).cumsum().to_numpy()+1e-10)
    deviation=signal(fair-price)
    high=rolling(deviation,20,.8);low=rolling(deviation,20,.2)
    return signal(np.where(deviation>=high,1.,np.where(deviation<=low,-1.,0.))),threshold


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--factors',required=True,type=Path)
    parser.add_argument('--source',required=True,type=Path);parser.add_argument('--formal-start',required=True)
    parser.add_argument('--output',required=True,type=Path);args=parser.parse_args()
    from alpha import FactorPlanState
    from alpha.factor import WarmupTimeline,warmup_requirements,required_history_start
    from server.modules.shared.factor_param_resolver import _resolve_frozen_factor
    from tools.factors.alpha_plan import alpha_plan_spec
    from tools.factors.expr.streaming.calendar_window import TradingCalendarWindow,TradingSession
    from tools.data.types import DataFreq
    frozen=json.loads(args.factors.read_text());refs={r['ref']:r for r in frozen['factors']}
    factor=_resolve_frozen_factor(refs[frozen['signal_ref']],username='alice',frozen_by_ref=refs)
    frame=pq.read_table(args.source,columns=['trade_timestamp','trading_day','close_price','adjustment_mul','adjustment_add']).to_pandas()
    times=frame.trade_timestamp.to_numpy(dtype=np.int64)*1000000;days=frame.trading_day.to_numpy()
    price=frame.close_price.to_numpy(dtype=float);adjusted=price*frame.adjustment_mul.to_numpy()+frame.adjustment_add.to_numpy()
    starts=np.r_[0,np.flatnonzero(days[1:]!=days[:-1])+1];ends=np.r_[starts[1:],len(times)]
    sessions=[TradingSession(str(days[a]),int(times[a])-60000000000,int(times[b-1]),int(b-a)) for a,b in zip(starts,ends)]
    spec=alpha_plan_spec(factor.expr,source_freq=DataFreq.MIN1,products=('audit',),session_calendar=TradingCalendarWindow(tuple(sessions)))
    nodes=spec['nodes'];threshold=next(i for i,n in enumerate(nodes) if n['kind']=='signal' and nodes[n['child']]['kind']=='session_rolling' and nodes[n['child']]['lookback_sessions']==250)
    spec['outputs']=[spec['outputs'][0],threshold];payload={k:v for k,v in spec.items() if k!='key_tuples'}
    formal=pd.Timestamp(args.formal_start).value;first=int(np.searchsorted(times,formal))
    exact=WarmupTimeline(times,days).required_start(spec,trading_start_ns=formal)
    bound=required_history_start(warmup_requirements(spec),trading_start_ns=formal,sessions=[(s.start_ns,s.end_ns,s.bar_count) for s in sessions])
    def replay(start):
        state=FactorPlanState(json.dumps(payload),1);row=np.empty(len(spec['columns']));boundary=np.zeros(len(spec['boundaries']),dtype=np.uint8)
        result=np.empty((len(times)-first,2));started=time.perf_counter()
        for i in range(start,len(times)):
            for j,column in enumerate(spec['columns']):row[j]=adjusted[i] if column=='CLOSE_ADJUSTED' else price[i]
            boundary[:]=i==start or days[i]!=days[i-1]
            value=state.update_context(int(times[i]),row,boundary)
            if i>=first:result[i-first]=value
        return result,time.perf_counter()-started
    full,seconds=replay(0);suffix,subset_seconds=replay(int(np.searchsorted(times,bound)))
    expected,expected_threshold=oracle(times,days,price,adjusted)
    comparisons={
        'formal_signal_mismatches':int(np.count_nonzero(full[:,0]!=expected[first:])),
        'warmup_suffix_signal_mismatches':int(np.count_nonzero(full[:,0]!=suffix[:,0])),
        'formal_threshold_nonfinite':int(np.count_nonzero(~np.isfinite(full[:,1]))),
        'threshold_max_abs_error':float(np.nanmax(np.abs(full[:,1]-expected_threshold[first:]))),
        'warmup_suffix_threshold_max_abs_error':float(np.nanmax(np.abs(full[:,1]-suffix[:,1])))}
    result=dict(source=str(args.source),rows=len(times),days=len(starts),formal_start=args.formal_start,
        data_start_utc=pd.Timestamp(times[0],unit='ns',tz='UTC').isoformat(),data_end_utc=pd.Timestamp(times[-1],unit='ns',tz='UTC').isoformat(),
        exact=exact,conservative_start_ns=bound,nodes=len(nodes),comparisons=comparisons,
        diagnostic_binding_seconds=seconds,suffix_binding_seconds=subset_seconds,
        limitation='test-only Rust binding vs independent oracle; not a native strategy Job, no returns claim')
    with args.output.open('x') as handle:json.dump(result,handle,indent=2)
    print(json.dumps(result))
    assert comparisons['formal_signal_mismatches']==comparisons['warmup_suffix_signal_mismatches']==comparisons['formal_threshold_nonfinite']==0
    assert comparisons['threshold_max_abs_error']<1e-10 and comparisons['warmup_suffix_threshold_max_abs_error']<1e-10

if __name__=='__main__':main()
