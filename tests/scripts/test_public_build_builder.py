import json
from types import SimpleNamespace
import pytest
from scripts.server.public_build_builder import prepare, validate_limits, MEMORY


def limits(**changes):
    return {'HostConfig': {'Memory': MEMORY, 'MemorySwap': MEMORY,
                          'CpuPeriod': 100000, 'CpuQuota': 200000, **changes}}


@pytest.mark.parametrize('changes', [{'Memory':0}, {'MemorySwap':-1}, {'CpuQuota':0}])
def test_rejects_unlimited_existing_builder(changes):
    with pytest.raises(RuntimeError): validate_limits(limits(**changes))


def test_creates_native_bounded_builder_and_checks_actual_runtime_limits():
    calls=[]
    def run(args, **kwargs):
        calls.append(args)
        if args[1:3]==['buildx','inspect'] and '--bootstrap' not in args:
            return SimpleNamespace(returncode=1,stdout='',stderr='no builder found')
        return SimpleNamespace(returncode=0,stdout=json.dumps([limits()]) if args[1]=='inspect' else '',stderr='')
    assert prepare(run, headroom=lambda: None)=='tr-public-bounded'
    create=next(c for c in calls if c[1:3]==['buildx','create'])
    assert 'memory=2g' in create and 'memory-swap=2g' in create
    assert 'default-load=true' in create
    assert '--buildkitd-config' in create
    assert calls[-1][1]=='inspect'


def test_daemon_failure_never_replaces_existing_builder():
    calls=[]
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=int(args[1]=='buildx'),stdout='',stderr='daemon unavailable')
    with pytest.raises(RuntimeError):prepare(run, headroom=lambda: None)
    assert not any(c[1:3]==['buildx','create'] for c in calls)


def test_existing_builder_uses_inspect_supported_by_older_buildx():
    def run(args, **kwargs):
        assert kwargs['timeout'] == 180
        assert '--format' not in args or args[1] == 'info'
        if args[1:3] == ['buildx', 'inspect']:
            return SimpleNamespace(returncode=0, stdout='Name: tr-public-bounded\nDriver: docker-container\n', stderr='')
        return SimpleNamespace(returncode=0, stdout=json.dumps([limits()]) if args[1]=='inspect' else '', stderr='')
    assert prepare(run, headroom=lambda: None) == 'tr-public-bounded'


def test_headroom_fails_before_host_pressure_and_does_not_count_swap(tmp_path):
    from scripts.server.public_build_builder import require_host_headroom
    meminfo = tmp_path / 'meminfo'
    meminfo.write_text('MemAvailable: 2300000 kB\nSwapFree: 9999999 kB\n')
    with pytest.raises(RuntimeError, match='available RAM'):
        require_host_headroom(meminfo)
    meminfo.write_text('MemAvailable: 3000000 kB\n')
    require_host_headroom(meminfo)


def test_keycloak_requires_reserved_address_on_manager_network():
    import yaml
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    services = yaml.safe_load((root/'deploy/docker/keycloak/compose.yaml').read_text())['services']
    network = services['keycloak']['networks']['manager']
    assert 'TR_IDENTITY_MANAGER_IPV4:?' in network['ipv4_address']
    assert network['aliases'] == ['tr-keycloak']


def test_native_builder_reuses_only_trusted_https_daemon_mirror_configuration():
    from scripts.server.public_build_builder import builder_config
    import tomllib
    value = tomllib.loads(builder_config(['https://mirror.example/']))
    assert value['registry']['docker.io']['mirrors'] == ['mirror.example']
    assert value['worker']['oci']['max-parallelism'] == 1
    for invalid in ['http://mirror.example', 'https://user:secret@mirror.example',
                    'https://mirror.example/path', 'https://mirror.example/?token=secret']:
        with pytest.raises(ValueError): builder_config([invalid])
