"""Opt-in compatibility match benchmark; full output checked against scalar oracle."""
from pathlib import Path
import argparse,json,resource,sys,time
import numpy as np
import pandas as pd
from tools.factors.expr import EvaluateContext, CANDIDATE,CURRENT,scope_bars
from tools.data.types import DataFreq
from tests.factors.test_bar_search import _FrameExpr

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--rows',type=int,default=20000);parser.add_argument('--window',type=int,default=60)
    args=parser.parse_args();values=np.arange(args.rows,dtype=float)%197
    frame=pd.DataFrame({'A':values},index=pd.date_range('2026-01-01',periods=args.rows,freq='min'))
    expr=_FrameExpr(frame).bar_distance(CANDIDATE<CURRENT,scope=None,lookback=args.window,default=999)
    ctx=EvaluateContext(products=('A',),freq=DataFreq.MIN1,cache={})
    started=time.perf_counter();actual=expr.evaluate(ctx=ctx);elapsed=time.perf_counter()-started
    expected=[]
    for t,v in enumerate(values):
        expected.append(next((t-j for j in range(t-1,max(-1,t-args.window-1),-1) if values[j]<v),999))
    np.testing.assert_equal(actual['A'].to_numpy(),expected)
    rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1024 if sys.platform.startswith('linux') else 1)
    result=dict(rows=args.rows,window=args.window,seconds=elapsed,peak_rss_bytes=rss,
                note='synthetic deterministic compatibility batch; includes adapter/compile; excludes scalar oracle time')
    args.output.write_text(json.dumps(result));print(json.dumps(result))
if __name__=='__main__':main()
