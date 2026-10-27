"""Opt-in real Celery/RabbitMQ/native-strategy acceptance; localhost only.

Uses an already staged real T/TL manifest. Creates an isolated Job DB, worker
process, queue and CouchDB database. No eager tasks, mock executor or source
registry writes. Broker/CouchDB must be dedicated test instances, not production.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import urllib.parse
import uuid

import orjson


def localhost(url):
    if urllib.parse.urlparse(url).hostname not in {'127.0.0.1','localhost','::1'}:
        raise ValueError('acceptance endpoints must be dedicated localhost instances')
    return url


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--broker',type=localhost,required=True)
    parser.add_argument('--couch-url',type=localhost,required=True)
    parser.add_argument('--credentials-file',type=Path,required=True)
    parser.add_argument('--complex-match',action='store_true',help='exercise nested SignalAlign/Where and partitioned Rust search')
    parser.add_argument('--family-mode',choices=['mixed','group','threshold'],default='mixed')
    args=parser.parse_args();args.root.mkdir(parents=True,exist_ok=False)
    credentials=json.loads(args.credentials_file.read_text())
    def request(method,path,data=None):
        token=base64.b64encode(f"{credentials['username']}:{credentials['password']}".encode()).decode()
        request=urllib.request.Request(args.couch_url.rstrip('/')+path,data=data,method=method,headers={'Authorization':'Basic '+token})
        with urllib.request.urlopen(request,timeout=10) as response:return json.loads(response.read())
    deployment='acceptance-'+uuid.uuid4().hex[:12];database=deployment.replace('-','_')
    request('PUT','/'+database)
    env={k:v for k,v in os.environ.items() if not k.startswith(('FACTORTESTER_','TRADERESEARCH_','GTHT_JOB_'))}
    env.update(FACTORTESTER_BROKER_URL=args.broker,FACTORTESTER_JOB_QUEUE='tr.acceptance',
        FACTORTESTER_DEPLOYMENT_ID=deployment,FACTORTESTER_SERVICE_PORT='8000',
        FACTORTESTER_JOB_DB=str((args.root/'jobs.sqlite').resolve()),
        FACTORTESTER_NAUTILUS_CATALOG_ROOT=str(args.manifest.parent.resolve()),
        GTHT_JOB_ARTIFACT_ROOT=str((args.root/'artifacts').resolve()),
        FACTORTESTER_COUCHDB_URL=args.couch_url,FACTORTESTER_COUCHDB_DB=database,
        FACTORTESTER_COUCHDB_USER=credentials['username'],FACTORTESTER_COUCHDB_PASSWORD=credentials['password'])
    # Resolve the actual embedded family, not a substituted expression/executor.
    from tests.server.test_factor_param_resolver import _frozen_probe
    source='''from tools.factors import FactorFamily
from tools.data.types import DataColumn
from tools.factors.FactorExpr import ColumnRef
from tools.factors.expr.signal_align import SignalAlign
class VersionProbe(FactorFamily):
    signal_freq = "30m"
    @staticmethod
    def factor_expr():
        return SignalAlign(ColumnRef(DataColumn.CLOSE).rolling('20m').mean(),'30m')
'''
    if args.complex_match:
        source=source.replace("from tools.factors.expr.signal_align import SignalAlign", "from tools.factors.expr.signal_align import SignalAlign\nfrom tools.factors.expr import CURRENT,CANDIDATE,scope_bars\nfrom tools.factors.expr.conditional import where")
        source=source.replace("return SignalAlign(ColumnRef(DataColumn.CLOSE).rolling('20m').mean(),'30m')", "price=ColumnRef(DataColumn.CLOSE)\n        formed=SignalAlign(price.rolling(2).mean(),'3m')\n        predicate=where(CURRENT>CANDIDATE,(CURRENT-CANDIDATE)>formed/100000,False)\n        return price.bar_distance(predicate,scope=scope_bars(120),lookback=60,default=60)")
    frozen={**_frozen_probe(source),'source_kind':'transient','source_code':source,'temporary':True}
    manifest=json.loads(args.manifest.read_text());catalogs={};receipts=[]
    for item in manifest['products']:
        folder=Path(item['catalog_path']).resolve()
        if not folder.is_relative_to(args.manifest.parent.resolve()):raise ValueError('catalog escapes isolated fixture root')
        receipt=json.loads((folder/'factor_tester_catalog_receipt.json').read_text());receipts.append(receipt)
        catalogs[item['product']]={'catalog_dir':str(folder),'contract_uid':receipt['contract_uid']}
    from tests.server.test_nautilus_bridge_config import _minimal_frozen
    from server.services.nautilus_bridge.config import freeze_instrument_execution_policy
    import pandas as pd
    ids=['Group-1','Group-2'] if args.family_mode=='group' else ['Threshold-1'] if args.family_mode=='threshold' else ['Group-1','Group-2','Threshold-1']
    settings=_minimal_frozen(instrument_execution_policy=freeze_instrument_execution_policy(preset='basic').manifest(),
        start_utc=pd.Timestamp(min(x['first_available_ns'] for x in receipts),tz='UTC').isoformat(),
        end_utc=pd.Timestamp(max(x['last_available_ns'] for x in receipts),tz='UTC').isoformat(),
        venues=[dict(name='CFFEX',account_type='MARGIN',oms_type='HEDGING',starting_balances=['1000000 CNY'],base_currency='CNY')],
        strategy_venue_bindings=[dict(strategy_id=s,venue_ids=['CFFEX'],product_scope_refs=['product-group:treasuries']) for s in ids])
    run_spec={'run_spec_version':10,'configuration':{'shared':{'factors':[frozen],
        'product_selections':{'product-group:treasuries':{'paths':[r['contract_uid'] for r in receipts]}}},
        'analyses':{'backtest':{'execution':{'backend':'nautilus_trader','contract_version':4,
            'nautilus_contract':{'settings':settings}}}}}}
    families=[dict(strategy_id=f'Group-{i}',kind='cross_sectional_group',parameters=dict(split_count=2,group_index=i),
                   factor_roles={'signal':{'ref':frozen['ref']}}) for i in (1,2)]
    families.append(dict(strategy_id='Threshold-1',kind='threshold',parameters={'entry_threshold':2 if args.complex_match else 100,'exit_threshold':1 if args.complex_match else 99},factor_roles={'signal':{'ref':frozen['ref']}}))
    families=[family for family in families if family['strategy_id'] in ids]
    plan={'plan_version':1,'kind':'nautilus_strategy_family','strategy_families':families,
          'catalog_inputs':catalogs,'max_input_bars':manifest['expected_slices']}
    job_spec={'_owner':'alice','run_spec':run_spec}
    from server.jobs.models import JobRecord
    from server.jobs.states import JobStatus
    from server.jobs.repository.sqlite import JobRepository
    from server.jobs.assurance import canonical_hash
    from server.services.research_run_identity import hash_run_spec
    from server.jobs.dispatch.contract import DispatchMessage
    from server.jobs.dispatch.celery_app import create_app,TASK_NAME
    repo=JobRepository(env['FACTORTESTER_JOB_DB']);job_id=deployment+'-native'
    record=JobRecord(job_id=job_id,run_id=deployment+'-run',owner='alice',workspace_id=deployment,
        kind='backtest',status=JobStatus.SUBMITTED,deployment_id=deployment,service_port=8000,
        runner_path='server.modules.single_factor_test.process_runners:run_group',retention_mode='full',
        job_spec=job_spec,job_spec_hash=canonical_hash(job_spec),run_spec_hash=hash_run_spec(run_spec),
        execution_plan=plan,execution_plan_hash=canonical_hash(plan))
    repo.create(record);repo.transition(job_id,JobStatus.PLANNING);repo.transition(job_id,JobStatus.QUEUED)
    app=create_app(broker_url=args.broker,queue='tr.acceptance',target_deployment=deployment,target_port=8000)
    started=time.perf_counter();sampled_rss=[]
    with (args.root/'worker.log').open('w') as log:
        worker=subprocess.Popen([sys.executable,'-m','celery','-A','server.jobs.dispatch.worker_app:app','worker',
            '--pool=solo','--concurrency=1','--loglevel=INFO','--without-gossip','--without-mingle','--without-heartbeat'],env=env,stdout=log,stderr=subprocess.STDOUT)
        try:
            message=DispatchMessage(job_id,1,deployment,record.run_spec_hash,record.job_spec_hash,8000)
            task=app.send_task(TASK_NAME,args=[message.to_dict()])
            deadline=time.monotonic()+90
            while time.monotonic()<deadline:
                current=repo.require(job_id)
                raw=subprocess.check_output(['ps','-o','rss=','-p',str(worker.pid)],text=True).strip()
                if raw:sampled_rss.append(int(raw)*1024)
                if current.status in {JobStatus.SUCCEEDED,JobStatus.FAILED,JobStatus.CANCELLED}:break
                if worker.poll() is not None:raise RuntimeError('worker exited; inspect isolated worker.log')
                time.sleep(.2)
            if current.status is not JobStatus.SUCCEEDED:raise AssertionError(f'Job {current.status}: {current.error}')
            result=current.result_summary
            assert result['factor_actors']==1 and result['python_factor_bar_callbacks']==0
            if args.complex_match:
                assert result['factor_plan_nodes']==5
                assert {slots['signal'] for slots in result['strategy_output_slots'].values()}=={0}
            assert result['strategy_publications']==[manifest['expected_slices']]*len(ids)
            assert result['rank_passes']==(0 if args.family_mode=='threshold' else manifest['expected_slices'])
            assert result['orders']>0
            ref=result.get('report_ref');assert ref,'successful Job must publish its report'
            report=request('GET','/'+database+'/'+urllib.parse.quote(ref,safe=':'))
            (args.root/'couch-report.json').write_text(json.dumps(report,indent=2))
            assert report['job_id']==job_id and report['owner']=='alice'
            assert set(report['attachments']) >= {'tearsheet.html','orders.csv','fills.csv','positions.csv','account.csv'}
            for name,stored in report['attachments'].items():
                from server.jobs.storage.couchdb_reports import CouchDBObjectStore
                store=CouchDBObjectStore(args.couch_url,database,username=credentials['username'],password=credentials['password'])
                data=store.get_attachment(ref,stored)
                assert hashlib.sha256(data).hexdigest()==stored.split('.')[0]
            receipt={'complex_match':args.complex_match,'family_mode':args.family_mode,'job_id':job_id,'task_id':task.id,'status':current.status.value,'seconds':time.perf_counter()-started,
                'sampled_worker_rss_max_bytes':max(sampled_rss,default=0),'worker_pid':worker.pid,'terminal_worker_pid':current.worker_pid,'result':result,
                'couchdb_database':database,'verified_attachments':sorted(report['attachments']),
                'limits':'local isolated execution of frozen plan; authoring/planning HTTP and production deployment not covered'}
            (args.root/'receipt.json').write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt))
        finally:
            worker.terminate()
            try:worker.wait(timeout=15)
            except subprocess.TimeoutExpired:worker.kill();worker.wait()
            # Only this invocation's unique queue; keep Job DB/report receipts for inspection.
            app.amqp.queues.select([app.conf.task_default_queue])
            with app.connection_for_write() as connection:
                connection.default_channel.queue_delete(app.conf.task_default_queue)


if __name__=='__main__':main()
