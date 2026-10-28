"""Real isolated Manager peer API -> RabbitMQ/Celery -> native node -> CouchDB.

Reuses an explicitly supplied frozen real-data fixture Job as research input.
No eager tasks or replacement executor. No production endpoints accepted.
"""
from __future__ import annotations
import argparse
import copy
from dataclasses import asdict
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import urllib.parse
import urllib.error
import urllib.request
import uuid


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--automatic',action='store_true')
    parser.add_argument('--saved-plan',action='store_true',help='Save/reopen/resolve the editable document before real dispatch')
    parser.add_argument('--federated',action='store_true')
    parser.add_argument('--fixture-db',type=Path,required=True)
    parser.add_argument('--fixture-job',required=True)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--broker',required=True)
    parser.add_argument('--couch-url',required=True)
    parser.add_argument('--credentials-file',type=Path,required=True)
    parser.add_argument('--compare-with',type=Path)
    parser.add_argument('--oidc-fixture-dir',type=Path,required=True)
    parser.add_argument('--manager-id',choices=['manager-a','manager-b'],default='manager-a')
    parser.add_argument('--node-client',choices=['node-a','node-b'],default='node-a')
    args=parser.parse_args()
    for url in (args.broker,args.couch_url):
        if urllib.parse.urlparse(url).hostname not in {'127.0.0.1','localhost'}:
            raise ValueError('isolated localhost services required')
    args.root.mkdir(parents=True,exist_ok=False)
    import settings
    settings.CACHE_DB_PATH=args.root/'private-metadata.sqlite';settings.CACHE_DIR=args.root
    from server.jobs.repository.sqlite import JobRepository
    from server.jobs.models import JobRecord
    from server.jobs.states import JobStatus
    from server.jobs.assurance import canonical_hash
    from server.jobs.dispatch.node_service import ExecutionNodeService
    from server.jobs.dispatch.remote import RemoteJobRepository
    from server.jobs.dispatch.planning import PlanningDispatcher
    from server.jobs.dispatch.dispatcher import DispatchRunner,KombuPublisher
    from server.jobs.dispatch.outbox import DispatchOutbox
    from server.manager.http.peer_handler import PeerControlHandler
    from server.identity.service_access import ServiceHTTPClient,ServiceTokenVerifier
    from server.identity.keycloak import ServiceOIDCClient
    from traderesearch_data.execution import BarRequirement,BundleInstallation,BarOffer,ServiceDeployment
    from traderesearch_data.bundles import bundle_content_fingerprint
    from sources.registry import installed_bundles
    fixture=JobRepository(args.fixture_db).require(args.fixture_job)
    old_plan=fixture.execution_plan
    credentials=json.loads(args.credentials_file.read_text())
    os.environ.update(GTHT_JOB_ARTIFACT_ROOT=str(args.root/'manager-artifacts'),
        FACTORTESTER_COUCHDB_URL=args.couch_url,FACTORTESTER_COUCHDB_DB='tr_remote_'+uuid.uuid4().hex,
        FACTORTESTER_COUCHDB_USER=credentials['username'],FACTORTESTER_COUCHDB_PASSWORD=credentials['password'])
    from server.jobs.storage.couchdb_reports import CouchDBObjectStore
    store=CouchDBObjectStore(args.couch_url,os.environ['FACTORTESTER_COUCHDB_DB'],username=credentials['username'],password=credentials['password'])
    import base64
    req=urllib.request.Request(args.couch_url+'/'+store.database,data=b'',method='PUT',headers={'Authorization':'Basic '+base64.b64encode(f"{credentials['username']}:{credentials['password']}".encode()).decode()})
    with urllib.request.urlopen(req):pass
    manager=args.manager_id;node={"node-a":"node-b","node-b":"node-c"}[args.node_client]
    os.environ['FACTORTESTER_JOB_DB']=str(args.root/'manager-jobs.sqlite')
    os.environ['FACTORTESTER_SERVER_ID']=manager
    settings.CACHE_DB_PATH=args.root/'manager-jobs.sqlite'
    repo=JobRepository(settings.CACHE_DB_PATH)
    issuer='http://127.0.0.1:8098/realms/tr-node-test'
    manager_client='manager-api' if manager=='manager-a' else 'manager-b-api'
    def oidc(client):
        return ServiceOIDCClient('http://127.0.0.1:8098','tr-node-test',client,
            client_secret=(args.oidc_fixture_dir/(client+'.secret')).read_text().strip())
    from server.manager.services.test_authoring import TestAuthoringService
    origin = 'manager-a' if manager == 'manager-b' else 'manager-b'
    state=SimpleNamespace(test_authoring=TestAuthoringService(),
        federation_registry=SimpleNamespace(servers=lambda **_: [{'server_id':origin}]),session=lambda _token:None,server_id=manager,job_repository=repo,
        execution_token_verifier=ServiceTokenVerifier(oidc(manager_client),issuer=issuer,audience=manager))
    class Handler(PeerControlHandler):pass
    Handler.state=state
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    endpoint=f'http://127.0.0.1:{server.server_port}'
    client=ServiceHTTPClient(endpoint,oidc=oidc(args.node_client),response_limit=16*1024**2)
    bundle=next(bundle for bundle in installed_bundles() if bundle.bundle_id=='Local')
    installation=BundleInstallation(manager,node,'local-fixture','Local',bundle.version,bundle_content_fingerprint(bundle),'platform')
    target=ServiceDeployment(manager,node,'native-backtest','candidate-v1',('backtest',))
    offers=[];requirements=[];catalogs={}
    for item in old_plan['catalog_inputs'].values():
        receipt=json.loads((Path(item['catalog_dir'])/'factor_tester_catalog_receipt.json').read_text())
        uid=item['contract_uid'];catalogs[uid]=item
        req=BarRequirement(uid,'1-MINUTE-LAST-EXTERNAL','raw','interval-end-available-at-close',('open','high','low','close','volume'),receipt['first_available_ns'],receipt['last_available_ns'])
        requirements.append(req)
        offers.append(BarOffer(installation,'LocalCNFuturesContractMIN1',uid,req.bar_spec,req.price_basis,req.time_semantics,req.fields,req.start_ns,req.end_ns,True))
    from tests.nautilus_source_fixture import resolved_contract_minute_source
    adapter=resolved_contract_minute_source().adapter
    runtime={key:getattr(adapter,key) for key in ('member_key','adapter_id','frequency','instrument_scope','clock_policy')}
    descriptor={'target':asdict(target),'service_port':8000,'offers':[asdict(x) for x in offers],
        'runtime_adapters':{x.source_ref:runtime for x in offers},
        # Staged source fixture is node-local only; never sent at registration.
        'catalog_inputs':catalogs}
    descriptor_path=args.root/'node-descriptor.json';descriptor_path.write_text(json.dumps(descriptor))
    remote=RemoteJobRepository(client,descriptor);route=remote.register()
    service=ExecutionNodeService(repo,manager_id=manager)
    binding=service.bind(target=asdict(target),requirements=[asdict(x) for x in requirements],
        selections={x.product_ref:offers[i].source_ref for i,x in enumerate(requirements)},test_type='backtest')
    run_spec=copy.deepcopy(fixture.job_spec['run_spec'])
    from server.modules.shared.factor_param_utils import unique_frozen_factor_records
    shared=run_spec['configuration']['shared']
    shared['factors']=unique_frozen_factor_records(shared['factors'])
    run_spec['data_requirements']=[asdict(x) for x in requirements]
    backtest=run_spec['configuration']['analyses']['backtest'];execution=backtest['execution']
    contract=execution['nautilus_contract'];execution.update(backend='nautilus_trader',contract_version=4)
    contract.update(contract_version=2,blockers=[],source_adapter={'feed_kind':'bar','bar_spec':requirements[0].bar_spec})
    settings=contract['settings'];settings.pop('data_source_ref',None);settings['data_requirement_ref']='data-requirements:'+canonical_hash([x.requirement_ref for x in requirements])
    scope='inline:treasuries' if args.saved_plan else settings['product_scope_refs'][0]
    old_scope=settings['product_scope_refs'][0]
    if args.saved_plan:
        def scope_refs(value):
            if isinstance(value,dict):return {key:scope_refs(item) for key,item in value.items()}
            if isinstance(value,list):return [scope_refs(item) for item in value]
            return scope if value==old_scope else value
        contract.update(scope_refs(contract))
        settings=contract['settings']
    settings['product_scope_refs']=[scope]
    run_spec['configuration']['shared']['product_selections']={scope:{'paths':list(catalogs)}}
    families=copy.deepcopy(old_plan['strategy_families'])
    backtest['groups']=[{'id':family['strategy_id'],'product_path_selection_id':scope} for family in families]
    specs=[{**family,'template_kind':family['kind']} for family in families]
    if args.saved_plan:
        backtest['venues']=copy.deepcopy(settings['venues'])
        for venue in backtest['venues']:
            venue.setdefault('native_config',{})['fee_model']={'type':'zero'}
        backtest['strategy_venue_bindings']=copy.deepcopy(settings['strategy_venue_bindings'])
        from server.services.factor_strategy_templates import factor_strategy_catalog
        catalog=factor_strategy_catalog()
        templates={item['kind']:item for item in catalog['items']}
        backtest['factor_strategy_bindings']=[dict(binding_id='binding-'+family['strategy_id'],
            strategy_id=family['strategy_id'],template_ref=templates[family['kind']]['template_ref'],
            revision_ref=templates[family['kind']]['revision_ref'],product_group_ref=scope,
            factor_bindings={role:value['ref'] for role,value in family['factor_roles'].items()},
            parameters={**{item['key']:item['default'] for item in templates[family['kind']]['parameters'] if 'default' in item},**family['parameters']}) for family in families]
    spec={'_owner':'alice','run_spec':run_spec,'execution_binding':binding,'strategy_specs':specs}
    job_id='remote-'+uuid.uuid4().hex[:12]
    if args.federated:
        from server.services.research_run_context import create_manager_run_context,MANAGER_RUN_CONTEXT_KEY
        from server.services.research_configurations import validate_payload
        from server.jobs.report_outputs import default_output_requests
        from server.manager.domain.federation import ServiceRoute
        from server.manager.domain.federation.gateway import FederatedGateway
        import hashlib,orjson
        # An origin Manager freezes this research input; the remote Manager
        # runs the exact production preview/submission adapters, not a mock.
        execution['settings']=copy.deepcopy(settings)
        if args.saved_plan:
            import pandas as pd
            execution['settings'].pop('data_requirement_ref',None)
            for side in ('start','end'):
                stamp=pd.Timestamp(settings[side+'_utc']).tz_convert('UTC')
                execution['settings'][side+'_date']=stamp.strftime('%Y-%m-%d')
                execution['settings'][side+'_time']=stamp.strftime('%H:%M:%S')
            execution['settings'].update(timezone='UTC',time_precision='exact',freq_mode='fixed',freq_fixed='MIN1',
                fee_mode='zero',slippage_mode='none',order_type='market',matching_model='auto',liquidity_mode='infinite')
        configuration=validate_payload({**run_spec['configuration'],'schema_version':3,'ui':{}})
        fingerprint=hashlib.sha256(orjson.dumps(configuration,option=orjson.OPT_SORT_KEYS)).hexdigest()
        run_spec.update(workspace_id='remote-fixture',configuration_id='remote-fixture-config',
            configuration_revision=1,configuration_fingerprint=fingerprint,analyses=['backtest'],configuration=configuration)
        prepared=dict(owner='alice',workspace_id=run_spec['workspace_id'],analyses=['backtest'],
            configuration=dict(configuration_id=run_spec['configuration_id'],revision=1,fingerprint=fingerprint,payload=configuration),
            frozen_configuration=dict(configuration_id=run_spec['configuration_id'],revision=1,fingerprint=fingerprint,payload=configuration),run_spec=run_spec,task_name='federated native acceptance',
            acting_profile_ref='',acting_profile_name='',retention_mode='full',step_mode=False,
            performance_profile=None,margin_execution_profile=None,output_requests=default_output_requests(['backtest']),
            strategy_specs=specs)
        from server.services.federated_factor_sources import portable_source_path
        portable = {}
        for factor in shared['factors']:
            source = factor['source_code']
            alias = factor['identity']['family_alias']
            owner = factor['owner_ref']
            canonical = owner + ':' + alias
            portable[canonical] = dict(canonical_family_ref=canonical, source_kind='custom',source_owner=owner,
                source_access_policy='owner',factor_id=alias,path=portable_source_path(canonical),
                source_code=source,source_sha256=hashlib.sha256(source.encode()).hexdigest(),source_bytes=len(source.encode()))
        prepared['portable_factor_sources'] = list(portable.values())
        if args.saved_plan:
            from server.services import research_configurations
            from server.services.execution_plans import document
            from server.manager.services.execution_plan_resolution import resolve
            from server.modules.single_factor_test.execution_nodes import visible_targets
            stored=research_configurations.create_workspace_configuration(owner='alice',workspace_id='remote-fixture',payload=configuration)
            editable=document(configuration)
            editable['execution']={'mode':'auto','manager_id':manager,'bundles':[{'bundle_id':'Local','owner':'platform'}]}
            resolved=resolve(state,owner='alice',request={'workspace_id':'remote-fixture','execution_plan':editable})
            editable['execution'].update(resolved=resolved['binding'],resolved_ref=resolved['binding_ref'])
            path='/api/test-authoring/workspaces/remote-fixture/configuration'
            saved=state.test_authoring.write('PUT',path,owner='alice',payload={'expected_revision':stored['revision'],'execution_plan':editable})
            assert saved.status==200, saved
            reopened=state.test_authoring.get(path,owner='alice').payload['configuration']
            assert canonical_hash(reopened['execution_plan'])==canonical_hash(editable)
            prepared['configuration']=reopened
            prepared['execution_selection']=editable['execution']
            run_spec['data_requirements']=[item['requirement'] for item in resolved['binding']['inputs']]
            run_spec.update(configuration_id=reopened['configuration_id'],configuration_revision=reopened['revision'],configuration_fingerprint=reopened['fingerprint'])
            (args.root/'saved-execution-plan.json').write_text(json.dumps(editable,indent=2))
        context=create_manager_run_context(prepared,owner='alice')
        if args.saved_plan:
            context=state.test_authoring.prepare_run_context({
                'workspace_id':'remote-fixture','configuration_revision':reopened['revision'],
                'analyses':['backtest'],
                '_execution_capability_directory': visible_targets('alice'),
                'transient_factor_sources':[{'path':'custom_factors/'+factor['identity']['family_alias']+'.py','source_code':factor['source_code']} for factor in shared['factors']],
            },owner='alice')
            blocked=context['prepared']['run_spec']['configuration']['analyses']['backtest']['execution']['nautilus_contract']['blockers']
            if blocked:raise AssertionError(blocked)
        federation=FederatedGateway()
        origin_client='manager-api' if origin=='manager-a' else 'manager-b-api'
        federation._execution_clients={endpoint:ServiceHTTPClient(endpoint,oidc=oidc(origin_client),response_limit=16*1024**2)}
        peer=ServiceRoute(server_id=manager,role='feat',branch='fixture',revision='candidate-v1',port=0,
            remote=True,peer_control_endpoint=endpoint)
        directory=federation.public_data(peer,kind='execution',operation='targets',principal='alice')
        assert canonical_hash(directory['targets'][0]['target'])==canonical_hash(asdict(target))
        request={MANAGER_RUN_CONTEXT_KEY:context,'execution_selection':{'target':asdict(target),
            'sources':{x.product_ref:offers[i].source_ref for i,x in enumerate(requirements)}}}
        if args.automatic:
            request['execution_selection']={'mode':'auto','manager_id':manager}
        preview=federation.public_data(peer,kind='execution',operation='preview',principal='alice',payload={'request':request})
        if preview['status']!=200:raise AssertionError(preview)
        request['expected_execution_binding_ref']=preview['response']['execution_binding_ref']
        if args.saved_plan:
            (args.root/'preview-binding.json').write_text(json.dumps(preview['response']['execution_binding'],indent=2))
            assert request['expected_execution_binding_ref']==editable['execution']['resolved_ref']
        submitted=federation.public_data(peer,kind='execution',operation='submit',principal='alice',payload={'request':request})
        if submitted['status']!=202:raise AssertionError(submitted)
        job_id=submitted['response']['jobs'][0]['job_id']
        record=repo.require(job_id)
        assert record.run_spec_hash==preview['response']['run_spec_hash']
    else:
        record=repo.create(JobRecord(job_id=job_id,run_id='run-'+job_id,owner='alice',workspace_id='fixture',kind='backtest',status=JobStatus.SUBMITTED,
            deployment_id=route['route_id'],service_port=8000,runner_path='server.modules.single_factor_test.process_runners:run_group',
            source_revision='candidate-v1',job_spec=spec,run_spec_hash=canonical_hash(run_spec),retention_mode='full'))
    env={k:v for k,v in os.environ.items() if not k.startswith(('FACTORTESTER_','TRADERESEARCH_','GTHT_JOB_','TR_'))}
    env.update(TR_MANAGER_ENDPOINT=endpoint,TR_EXECUTION_NODE_ID=node,TR_OIDC_ISSUER=issuer,TR_OIDC_CLIENT_ID=args.node_client,
        TR_OIDC_CLIENT_SECRET_FILE=str(args.oidc_fixture_dir/(args.node_client+'.secret')),
        TR_NODE_DESCRIPTOR_FILE=str(descriptor_path),TR_NODE_STATE_DIR=str(args.root/'node-private'),
        FACTORTESTER_BROKER_URL=args.broker,FACTORTESTER_JOB_QUEUE='tr.remote.acceptance',
        FACTORTESTER_NAUTILUS_CATALOG_ROOT='/tmp',GTHT_JOB_ARTIFACT_ROOT=str(args.root/'node-artifacts'))
    publisher=KombuPublisher(args.broker,queue='tr.remote.acceptance')
    planner=PlanningDispatcher(repo,publisher,target_online=repo.worker_target_online)
    outbox=DispatchOutbox(repo.db_path);outbox.ensure_schema()
    dispatcher=DispatchRunner(outbox,publisher,target_online=repo.worker_target_online)
    started=time.perf_counter();rss=[]
    with (args.root/'worker.log').open('w') as log:
        worker=subprocess.Popen([sys.executable,'-m','celery','-A','server.jobs.dispatch.node_worker_app:app','worker','--pool=solo','--concurrency=1','--loglevel=INFO','--without-gossip','--without-mingle','--without-heartbeat'],env=env,stdout=log,stderr=subprocess.STDOUT)
        try:
            deadline=time.monotonic()+120
            while time.monotonic()<deadline:
                planner.run_once();dispatcher.run_once()
                current=repo.require(job_id)
                raw=subprocess.check_output(['ps','-o','rss=','-p',str(worker.pid)],text=True).strip()
                if raw:rss.append(int(raw)*1024)
                if current.status in {JobStatus.SUCCEEDED,JobStatus.FAILED,JobStatus.CANCELLED}:break
                if worker.poll() is not None:raise RuntimeError('worker exited; see isolated log')
                time.sleep(.2)
            if current.status is not JobStatus.SUCCEEDED:
                raise AssertionError(f'{current.status.value}: {current.error}')
            if args.federated:
                for suffix in ("", "/result", "/artifacts"):
                    response=federation.public_data(peer,kind='execution',operation='job',principal='alice',
                        payload={'job_id':job_id,'suffix':suffix})
                    assert response['status']==200, response
                try:
                    federation.public_data(peer,kind='execution',operation='job',principal='bob',payload={'job_id':job_id})
                except urllib.error.HTTPError as denied:
                    assert denied.code==403
                else:raise AssertionError('undelegated user accessed Job')
            result=current.result_summary
            assert result['factor_actors']==1 and result['python_factor_bar_callbacks']==0
            assert len(result['strategy_publications'])==len(families)
            assert result['orders']>0 and current.report_ref
            report=store.get_report(current.report_ref)
            for name,stored in report['attachments'].items():
                import hashlib
                data=store.get_attachment(current.report_ref,stored)
                assert hashlib.sha256(data).hexdigest()==stored.split('.')[0]
            import csv,io,hashlib
            fills=list(csv.DictReader(io.StringIO(store.get_attachment(current.report_ref,report['attachments']['fills.csv']).decode())))
            fields=['instrument_id','order_side','last_qty','last_px','commission','ts_event']
            normalized=[[row.get(key) for key in fields] for row in fills]
            if not fills or not all(any(value is not None for value in row) for row in normalized):
                raise AssertionError('fill comparison has no real execution fields')
            fill_digest=canonical_hash(normalized)
            receipt={'run_spec_hash':record.run_spec_hash,'fills_sha256':fill_digest,'fill_columns':list(fills[0]),'job_id' :job_id,'manager_id':manager,'node_id':node,'status':current.status.value,
                'seconds':time.perf_counter()-started,'sampled_worker_peak_rss_bytes':max(rss),
                'manager_job_db':str(repo.db_path),'node_has_manager_job_db':False,
                'saved_plan_roundtrip':args.saved_plan,'saved_configuration_runspec_compiler':args.saved_plan,'automatic_matching':args.automatic,'cross_manager_job_reads':args.federated,'cross_manager_discovery_preview_submit':args.federated,'origin_manager':origin if args.federated else manager,'real_broker':True,'real_native_strategy':True,'authenticated_http':True,'authentication':'real Keycloak service account and introspection',
                'orders':result['orders'],'factor_actors':result['factor_actors'],'strategies':len(families),
                'attachments':list(report['attachments']),'data_start_ns':min(x.start_ns for x in requirements),
                'data_end_ns':max(x.end_ns for x in requirements),
                'scope':'isolated native catalog fixture with real prices; no production deployment or original-paper acceptance'}
            if args.compare_with:
                prior=json.loads(args.compare_with.read_text())
                if not args.automatic:
                    assert prior['manager_id'] != manager and prior['node_id'] != node
                assert prior['run_spec_hash'] == record.run_spec_hash
                assert prior['fills_sha256'] == fill_digest
                assert prior['orders'] == result['orders']
                receipt['comparison_verified']=True
                receipt['equivalent_other_node_verified']=prior['manager_id'] != manager and prior['node_id'] != node
            (args.root/'receipt.json').write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt))
        finally:
            worker.terminate()
            try:worker.wait(timeout=15)
            except subprocess.TimeoutExpired:worker.kill();worker.wait()
            server.shutdown();server.server_close();thread.join(timeout=2)


if __name__=='__main__':main()
