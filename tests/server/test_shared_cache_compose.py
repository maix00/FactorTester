"""Static deployment contracts, not running-container memory measurements."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _service(project, name):
    return yaml.safe_load((ROOT/'deploy/docker'/project/'compose.yaml').read_text())['services'][name]


def _backing_cache_path(service):
    cache = service['environment']['TR_SHARED_DATA_CACHE_ROOT']
    matches = []
    for volume in service['volumes']:
        if isinstance(volume,str):
            source,target = volume.rsplit(':',1)
        else:
            source,target = volume.get('source',''),volume['target']
        if cache == target or cache.startswith(target+'/'):
            matches.append((len(target),source+cache[len(target):]))
    assert matches, 'cache must be backed by an existing shared host mount'
    return max(matches)[1]


def test_manager_and_worker_cache_backing_identity_and_policy_match():
    services = [_service('factortester-public','factortester-public'),
                _service('factortester-server','manager')]
    services += [_service('job-dispatch',name)
                 for name in ['dispatcher','worker-8000','worker-8001']]
    assert len({_backing_cache_path(service) for service in services}) == 1
    for key in ['FACTORTESTER_SERVER_ID','TR_EXECUTION_NODE_ID','TR_DATA_HOST_ROLE','TR_DATA_DEVICE_REF',
                'TR_SHARED_DATA_CACHE_BYTES','TR_SHARED_DATA_ENTRY_BYTES','TR_DATA_QUERY_CONCURRENCY']:
        assert len({str(service['environment'][key]) for service in services}) == 1, key
    assert services[0]['environment']['TR_DATA_HOST_ROLE'] == 'server'


def test_node_and_cache_domain_are_not_manager_identity():
    for project, name in [('factortester-public', 'factortester-public'),
                          ('factortester-server', 'manager'),
                          ('job-dispatch', 'worker-8000')]:
        env = _service(project, name)['environment']
        assert 'TR_EXECUTION_NODE_ID:' in env['TR_EXECUTION_NODE_ID']
        assert 'TR_SHARED_STORAGE_ID:' in env['TR_DATA_DEVICE_REF']
        assert 'FACTORTESTER_SERVER_ID' not in env['TR_DATA_DEVICE_REF']
