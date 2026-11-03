from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from scripts.server.public_prebuilt_image import inspect_prepared, verify_document_startup


def test_only_exact_release_inputs_reuse_image():
 labels={'org.opencontainers.image.revision':'release','org.traderesearch.nautilus.revision':'native','org.traderesearch.python-deps.identity':'deps'}
 def run(args,**kwargs):return SimpleNamespace(returncode=0,stdout=json.dumps([{'Id':'sha256:'+'a'*64,'Config':{'Labels':labels}}]))
 assert inspect_prepared('candidate',revision='release',nautilus_revision='native',python_deps_id='deps',run=run)=='sha256:'+'a'*64
 for key in labels:
  old=labels[key];labels[key]='other'
  with pytest.raises(ValueError,match='frozen release inputs'):
   inspect_prepared('candidate',revision='release',nautilus_revision='native',python_deps_id='deps',run=run)
  labels[key]=old


def test_missing_image_is_distinct_from_daemon_failure():
 def run(args,**kwargs):return SimpleNamespace(returncode=1,stderr='Error: No such image: candidate')
 assert inspect_prepared('candidate',revision='x',nautilus_revision='y',python_deps_id='z',run=run) is None
 def failure(args,**kwargs):return SimpleNamespace(returncode=1,stderr='Cannot connect to Docker daemon')
 with pytest.raises(RuntimeError,match='cannot inspect'):
  inspect_prepared('candidate',revision='x',nautilus_revision='y',python_deps_id='z',run=failure)


def test_activation_passes_pinned_native_revision_to_remote_image_build():
    root=Path(__file__).resolve().parents[2]
    script=(root/'scripts/server/activate_public_revision.sh').read_text()
    build=script.split('if [[ "$reuse_status" == "3" ]]; then',1)[1].split('elif [[ "$reuse_status"',1)[0]
    assert 'FACTORTESTER_NAUTILUS_VENDOR_REVISION="$nautilus_revision"' in build
    assert script.index('nautilus_revision="$(git') < script.index('cache_plan="$(sudo')


def test_document_startup_probe_is_bounded_and_uses_immutable_image():
    calls=[]
    def run(args,**kwargs):
        calls.append((args,kwargs))
        return SimpleNamespace(returncode=0,stdout='technical-docs-ready\n')
    identity='sha256:'+'a'*64
    verify_document_startup(identity,run=run)
    command,options=calls[0]
    for flag,value in [('--network','none'),('--memory','256m'),('--memory-swap','256m'),('--cpus','1')]:
        assert command[command.index(flag)+1]==value
    assert '--read-only' in command and '--volume' not in command and '--mount' not in command
    assert command[command.index('--entrypoint')+2]==identity
    assert options['timeout']==45
    assert calls[-1][0][:3]==['docker','rm','-f']


@pytest.mark.parametrize('failure',[False,True])
def test_document_startup_failure_and_timeout_never_activate_or_leak_probe(failure):
    import subprocess
    calls=[]
    def run(args,**kwargs):
        calls.append(args)
        if args[1]=='run':
            if failure:raise subprocess.TimeoutExpired(args,45)
            return SimpleNamespace(returncode=1,stdout='')
        return SimpleNamespace(returncode=0,stdout='')
    with pytest.raises((RuntimeError,subprocess.TimeoutExpired)):
        verify_document_startup('sha256:'+'b'*64,run=run)
    assert calls[-1][:3]==['docker','rm','-f']
