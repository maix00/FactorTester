"""Bounded long replay stress using explicitly SYNTHETIC cyclic OHLC/continuous clocks.

Staging is a separate process and never part of runtime RSS/time. This is not a
paper-return result, a real exchange calendar, or production/Celery acceptance.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path
import platform
import resource
import sys
import time
import numpy as np
from server.services.nautilus_bridge.backtest_runner import ReplayInput,_load_input


def stage(base_manifest,root,rows):
    from nautilus_trader.persistence import ParquetDataCatalog
    from nautilus_trader.model import Bar
    root.mkdir(exist_ok=False,parents=True)
    base=json.loads(base_manifest.read_text());products=[]
    for item in base['products']:
        old=Path(item['catalog_path']);receipt=json.loads((old/'factor_tester_catalog_receipt.json').read_text())
        if receipt['selected_count']>20000:raise ValueError('benchmark base must be bounded')
        _,catalog,_,instrument=_load_input(ReplayInput(old,receipt['contract_uid']))
        bars=catalog.query_bars(identifiers=[receipt['bar_type']])
        folder=root/item['product'];folder.mkdir(parents=True);target=ParquetDataCatalog(str(folder));target.write_instruments([instrument])
        start=bars[0].ts_event;init=start+(bars[0].ts_init-bars[0].ts_event);batch=[]
        for i in range(rows):
            source=bars[i%len(bars)]
            batch.append(Bar(bar_type=source.bar_type,open=source.open,high=source.high,low=source.low,
                close=source.close,volume=source.volume,ts_event=start+i*60000000000,ts_init=init+i*60000000000))
            if len(batch)==2048:target.write_bars(batch);batch.clear()
        if batch:target.write_bars(batch)
        files=[]
        for path in sorted(folder.rglob('*.parquet')):
            with path.open('rb') as handle:digest=hashlib.file_digest(handle,'sha256').hexdigest()
            files.append(dict(path=str(path.relative_to(folder)),bytes=path.stat().st_size,sha256=digest))
        frozen={**receipt,'selected_count':rows,'first_event_ns':start,'last_event_ns':start+(rows-1)*60000000000,
            'first_available_ns':init,'last_available_ns':init+(rows-1)*60000000000,'catalog_files':files,
            'session_summaries':[],'synthetic_stress_replay':True,'selected_bars_sha256':None,'metadata_provenance':'SYNTHETIC stress replay; cyclic OHLC, continuous clock; not exchange rules'}
        (folder/'factor_tester_catalog_receipt.json').write_text(json.dumps(frozen))
        products.append(dict(product=item['product'],catalog_path=str(folder),base_closes=[float(x.close) for x in bars]))
    (root/'manifest.json').write_text(json.dumps(dict(expected_slices=rows,products=products,label='SYNTHETIC stress replay')))



def stage_real(root, rows, contract_month=None):
    """Unaltered local T/TL minute prices and clocks; isolated metadata probe."""
    from tests.server.test_nautilus_bridge_backtest_runner import _real_catalog
    root.mkdir(exist_ok=False, parents=True)
    products=[]
    for code, month in (("T", "2403"), ("TL", "2406")):
        folder=root/code; folder.mkdir()
        replay_input=_real_catalog(folder, code=code, month=contract_month or month, count=rows, batch_bars=2048)
        _,catalog,receipt,_=_load_input(replay_input)
        # Only the small real acceptance fixture is retained by this benchmark's
        # independent oracle; production replay and long stress retain no history.
        bars=catalog.query_bars(identifiers=[receipt["bar_type"]])
        products.append(dict(product=code, catalog_path=str(replay_input.catalog_dir),
                             base_closes=[float(bar.close) for bar in bars]))
    (root/"manifest.json").write_text(json.dumps(dict(expected_slices=rows,products=products,
        label="REAL local T/TL prices/clocks; synthetic instrument probe rules; not paper-return reproduction")))


def replay(root,out,complex_match=False):
    from tools.factors.expr import CLOSE
    from server.services.nautilus_bridge.strategy_backtest import run_strategy_families_replay
    from server.services.nautilus_bridge.strategy_families import CrossSectionalGroup
    manifest=json.loads((root/'manifest.json').read_text());rows=manifest['expected_slices'];inputs={}
    for item in manifest['products']:
        folder=Path(item['catalog_path']);receipt=json.loads((folder/'factor_tester_catalog_receipt.json').read_text())
        inputs[item['product']]=ReplayInput(folder,receipt['contract_uid'])
    mean=CLOSE.rolling(20).semantics(min_periods=1).mean()
    median=CLOSE.rolling(4096).semantics(min_periods=1).median()
    if complex_match:
        from tools.factors.expr import CURRENT,CANDIDATE,scope_bars,SignalAlign
        from tools.factors.expr.conditional import where
        formed=SignalAlign(CLOSE.rolling(2).mean(),'3m')
        median=CLOSE.bar_distance(where(CURRENT>CANDIDATE,(CURRENT-CANDIDATE)>formed/100000,False),scope=scope_bars(120),lookback=60,default=60)
    refs={'signal':'factor:v2:'+'a'*43,'confirm':'factor:v2:'+'b'*43}
    strategies=[dict(strategy_id=f'Group-{i}',factor_bindings={'signal':mean,'confirm':median},factor_refs=refs,family=CrossSectionalGroup(2,i)) for i in (1,2)]
    out.mkdir(exist_ok=False,parents=True);started=time.perf_counter()
    result=run_strategy_families_replay(inputs=inputs,strategies=strategies,output_dir=out/'reports',max_bars=rows,
        batch_minutes=1024,inspect_outputs=True)
    elapsed=time.perf_counter()-started
    assert result['factor_actors']==1
    assert result['factor_plan_nodes']==(5 if complex_match else 3)
    assert result['strategy_publications']==[rows,rows] and result['rank_passes']==rows
    assert result['bars']==rows*len(inputs) and result['max_batch_bars']<=2048
    for role,window,operation in [('signal',20,np.mean),('confirm',4096,np.median)]:
        actual=result['latest_outputs']['Group-1'][role][2]
        expected=[]
        for item in manifest['products']:
            base=item['base_closes']
            if complex_match and role=='confirm':
                # Synthetic continuous minute grid, exact clock phase from catalog receipt.
                receipt=json.loads((Path(item['catalog_path'])/'factor_tester_catalog_receipt.json').read_text())
                end=int(receipt['last_event_ns']);start=int(receipt['first_event_ns'])
                target=end//180000000000*180000000000
                pos=(target-start)//60000000000
                threshold=np.mean([base[j%len(base)] for j in range(max(0,pos-1),pos+1)])/100000
                current=base[(rows-1)%len(base)]
                lo=max(((rows-1)//120)*120,rows-1-60)
                expected.append(next((rows-1-j for j in range(rows-2,lo-1,-1) if current>base[j%len(base)] and current-base[j%len(base)]>threshold),60))
            else:expected.append(operation([base[i%len(base)] for i in range(max(0,rows-window),rows)]))
        np.testing.assert_allclose(actual,expected,rtol=0,atol=1e-9)
    peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1024 if sys.platform.startswith('linux') else 1)
    inventory=None
    if complex_match:
        opened=closed=0
        with (out/'reports'/'positions.csv').open() as handle:
            for position in csv.DictReader(handle):
                if position['ts_closed']:closed+=1
                else:opened+=1
        assert opened<=len(strategies)*len(inputs),'HEDGING targets accumulated offsetting positions'
        inventory=dict(open_positions=opened,closed_positions=closed)
    value=dict(inventory=inventory,complex_match=complex_match,label=manifest['label'],rows_per_product=rows,seconds=elapsed,peak_rss_bytes=peak,
        runtime=dict(platform=platform.platform(),python=sys.version.split()[0]),result=result,
        cache='Nautilus defaults; unchanged; system cache not cleared',scope='local native long replay; staging excluded; no Celery/public claim')
    (out/'measurements.json').write_text(json.dumps(value,indent=2));print(json.dumps(value))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--stage-base',type=Path)
    parser.add_argument('--complex-match',action='store_true')
    parser.add_argument('--contract-month',help='stage this real contract month for both T and TL')
    parser.add_argument('--stage-real',action='store_true')
    parser.add_argument('--root',required=True,type=Path);parser.add_argument('--rows',type=int,default=10000)
    parser.add_argument('--output',type=Path);args=parser.parse_args()
    if args.stage_real:stage_real(args.root,args.rows,args.contract_month)
    elif args.stage_base:stage(args.stage_base,args.root,args.rows)
    else:
        if args.output is None:parser.error('--output required for replay')
        replay(args.root,args.output,args.complex_match)


if __name__=='__main__':main()
