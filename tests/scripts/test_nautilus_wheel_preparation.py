"""Canonical wheel names and composed cache identity; no native build."""
from pathlib import Path
import os
import shutil
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[2]

def run(command, cwd, **kwargs):
    return subprocess.run(command,cwd=cwd,text=True,capture_output=True,**kwargs)

def test_composed_identity_and_canonical_stage(tmp_path):
    root=tmp_path/'repo';root.mkdir()
    scripts=root/'scripts/server';scripts.mkdir(parents=True)
    for name in ['prepare_nautilus_wheel_for_build.sh','nautilus_build_identity.sh']:
        shutil.copy(ROOT/'scripts/server'/name,scripts/name)
    for folder in [root,root/'vendor/nautilus_trader',root/'vendor/py-alpha-lib']:
        folder.mkdir(parents=True,exist_ok=True)
        run(['git','init','-q'],folder,check=True)
        (folder/'seed').write_text('initial')
        run(['git','add','seed'],folder,check=True)
        run(['git','-c','user.name=Test','-c','user.email=test@example.invalid','commit','-qm','initial'],folder,check=True)
    helper=f'source "{scripts}/nautilus_build_identity.sh"; nautilus_build_identity "{root}" "{root}/vendor/nautilus_trader" linux/amd64'
    identity=run(['bash','-c',helper],root,check=True).stdout.strip()
    assert len(identity)==64
    assert run(['bash','-c',helper.replace('linux/amd64','linux/arm64')],root,check=True).stdout.strip()!=identity
    cache=tmp_path/'wheels';wheel_dir=cache/identity;wheel_dir.mkdir(parents=True)
    dest=root/'deploy/docker/factortester-public/wheels';dest.mkdir(parents=True)
    old=dest/'nautilus_trader-0-cp314-cp314-linux_x86_64.whl';old.write_bytes(b'old')
    env={**os.environ,'NAUTILUS_WHEEL_DIR':str(cache)}
    command=['bash',str(scripts/'prepare_nautilus_wheel_for_build.sh')]
    assert run(command,root,env=env).returncode!=0
    assert old.read_bytes()==b'old'
    name='nautilus_trader-2.0.0rc8-cp314-cp314-linux_x86_64.whl'
    with zipfile.ZipFile(wheel_dir/name,'w') as wheel:
        wheel.writestr('nautilus_trader-2.0.0rc8.dist-info/METADATA','Name: nautilus-trader\nVersion: 2.0.0rc8\n')
    result=run(command,root,env=env)
    assert result.returncode==0,result.stderr
    assert [p.name for p in dest.glob('*.whl')]==[name]
    assert (dest/name).read_bytes()==(wheel_dir/name).read_bytes()


def test_finished_wheel_hit_skips_capacity_checks_and_compilation(tmp_path):
    import hashlib
    root=tmp_path/'repo';scripts=root/'scripts/server';scripts.mkdir(parents=True)
    for name in ['native_wheel_build.sh','native_build_lock.py','nautilus_build_identity.sh']:
        shutil.copy(ROOT/'scripts/server'/name,scripts/name)
    (scripts/'check_local_build_capacity.sh').write_text('exit 44\n')
    for folder in [root,root/'vendor/nautilus_trader',root/'vendor/py-alpha-lib']:
        folder.mkdir(parents=True,exist_ok=True)
        run(['git','init','-q'],folder,check=True)
        (folder/'seed').write_text('initial')
        run(['git','add','seed'],folder,check=True)
        run(['git','-c','user.name=Test','-c','user.email=test@example.invalid','commit','-qm','initial'],folder,check=True)
    python_source=root/'vendor/nautilus_trader/python';python_source.mkdir();(python_source/'pyproject.toml').touch()
    identity=run(['bash','-c',f'source "{scripts}/nautilus_build_identity.sh"; nautilus_build_identity "{root}" "{root}/vendor/nautilus_trader" linux/amd64'],root,check=True).stdout.strip()
    out=tmp_path/'wheels';folder=out/identity;folder.mkdir(parents=True)
    wheel=folder/'nautilus_trader-2.0.0rc8-cp314-cp314-linux_x86_64.whl';wheel.write_bytes(b'test receipt content')
    (folder/'checksums.sha256').write_text(f'{hashlib.sha256(wheel.read_bytes()).hexdigest()}  {wheel}\n')
    command=['bash',str(scripts/'native_wheel_build.sh')]
    env={**os.environ,'NAUTILUS_WHEEL_DIR':str(out),'NAUTILUS_CACHE':str(tmp_path/'cache')}
    result=run(command,root,env=env)
    assert result.returncode==0,result.stderr
    assert 'cache=hit' in result.stdout
    assert 'elapsed_seconds=' in result.stdout
    wheel.write_bytes(b'tampered')
    result=run(command,root,env=env)
    assert result.returncode==44
    assert 'cache=miss' in result.stdout
