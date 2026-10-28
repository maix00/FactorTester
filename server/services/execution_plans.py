"""One editable ExecutionPlan embeds RunSpec and execution selection.

The existing workspace row is a storage codec, not another editable document.
Its ui metadata stores only the execution fields; RunSpec configuration bytes
are not duplicated. Frozen RunSpecs exclude this deployment-only metadata.
"""
from copy import deepcopy

_META = '_execution_plan'


def document(payload):
    configuration=deepcopy(payload)
    metadata=configuration.setdefault('ui',{}).pop(_META,{})
    analyses=metadata.get('analyses') or list(configuration.get('analyses') or {})[:1]
    return {'plan_version':2,'run_spec':{'analyses':analyses,'retention_mode':metadata.get('retention_mode','full'),
        'configuration':configuration},'execution':deepcopy(metadata.get('execution') or {'mode':'auto','manager_id':'','bundles':[]})}


def encode(value):
    if not isinstance(value,dict) or set(value)!={'plan_version','run_spec','execution'} or value['plan_version']!=2:
        raise ValueError('ExecutionPlan v2 with run_spec and execution is required')
    spec=value['run_spec'];execution=value['execution']
    if not isinstance(spec,dict) or set(spec)-{'analyses','retention_mode','configuration'}:
        raise ValueError('unsupported editable RunSpec fields')
    analyses=spec.get('analyses')
    if not isinstance(analyses,list) or len(analyses)!=1 or not isinstance(analyses[0],str):
        raise ValueError('one test type is required')
    retention=spec.get('retention_mode','full')
    if retention not in {'summary','full'}:raise ValueError('invalid result retention')
    if not isinstance(execution,dict) or set(execution)-{'mode','manager_id','target','bundles','resolved','resolved_ref'} or execution.get('mode') not in {'auto','manual'}:
        raise ValueError('invalid execution selection')
    if not isinstance(execution.get('manager_id'),str):raise ValueError('Manager scope must be text')
    bundles=execution.get('bundles')
    if not isinstance(bundles,list) or len(bundles)>64:raise ValueError('Bundle selection must be a bounded array')
    keys=[]
    for bundle in bundles:
        if not isinstance(bundle,dict) or set(bundle)!={'bundle_id','owner'} or any(not isinstance(v,str) or not v for v in bundle.values()):
            raise ValueError('Bundle requires identity and owner')
        keys.append((bundle['bundle_id'],bundle['owner']))
    if len(keys)!=len(set(keys)):raise ValueError('duplicate Bundle selection')
    from server.services.research_configurations import validate_payload
    payload=validate_payload(spec.get('configuration'))
    if analyses[0] not in payload['analyses']:raise ValueError('selected test type has no configuration')
    payload.setdefault('ui',{})[_META]={'analyses':analyses,'retention_mode':retention,'execution':deepcopy(execution)}
    return payload


def selection(payload):
    return deepcopy((payload.get('ui') or {}).get(_META) or {})


def strip_selection(payload):
    payload=deepcopy(payload)
    if isinstance(payload.get('ui'),dict):payload['ui'].pop(_META,None)
    return payload
