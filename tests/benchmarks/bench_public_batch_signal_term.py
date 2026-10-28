"""Same-input public batch benchmark. Baseline source is test-only, never a fallback."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import sys
import time
import types
import numpy as np
import pandas as pd
from alpha.factor import ColumnRef,EvalContext,SignalAlign,TermStructureExpr
from alpha.factor.inputs import TermCurve,TermPoint


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rows',type=int,default=20000)
    parser.add_argument('--baseline-ref')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.rows<1:parser.error('rows must be positive')
    root=Path(__file__).resolve().parents[2]/'vendor/py-alpha-lib'
    signal,term=SignalAlign,TermStructureExpr
    if args.baseline_ref:
        def load(name):
            module=types.ModuleType('alpha.factor._test_baseline_'+name);module.__package__='alpha.factor'
            source=subprocess.check_output(['git','show',f'{args.baseline_ref}:py-binding/python/alpha/factor/{name}.py'],cwd=root,text=True)
            source=source.replace('FactorExpr.signal_align = _method','')
            exec(compile(source,f'baseline:{name}','exec'),module.__dict__)
            return module
        signal=load('signal').SignalAlign;term=load('term').TermStructureExpr
    times=pd.date_range('2026-01-01',periods=args.rows,freq='s')
    prices=np.arange(args.rows,dtype=float)
    curves=tuple(TermCurve('A',(TermPoint({'CLOSE':float(i+10)},10),TermPoint({'CLOSE':8.0},20)),times[i*100].value)
                 for i in range((args.rows+99)//100))
    ctx=EvalContext(products=('A',),preloaded={'A':pd.DataFrame({'CLOSE':prices},index=times)},term_curves={'A':curves})
    results={};receipts={}
    for name,expression in [('signal',signal(ColumnRef('CLOSE'),'30s')),('term',term('term_spread'))]:
        started=time.perf_counter();frame=expression.evaluate(ctx);elapsed=time.perf_counter()-started
        expected=(frame.index.as_unit('ns').asi8-times[0].value)/1e9 if name=='signal' else np.arange(args.rows)//100+2.0
        np.testing.assert_allclose(frame['A'].to_numpy(),expected,rtol=0,atol=1e-12)
        receipts[name]={'seconds':elapsed,'output_rows':len(frame),'sha256':hashlib.sha256(frame['A'].to_numpy().tobytes()).hexdigest()}
        results[name]=frame
    peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1024 if sys.platform.startswith('linux') else 1)
    value={'rows':args.rows,'snapshots':len(curves),'baseline_ref':args.baseline_ref,'python':sys.version.split()[0],
        'elapsed':receipts,'peak_rss_bytes':peak,'scope':'public batch only; synthetic deterministic data; full requested outputs retained'}
    args.output.write_text(json.dumps(value,indent=2));print(json.dumps(value))


if __name__=='__main__':main()
