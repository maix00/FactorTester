#!/usr/bin/env python3
"""Assemble an app-only image over a verified immutable runtime, without wheels.

Dependency, native, OS-tool and entrypoint changes require the ordinary build.
Only committed application bytes and their thin CLI bytecode can be replaced.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import select
import shutil
import subprocess
import tempfile
import time

MAX_FILE = 8 * 1024**2
MAX_PATCH = 32 * 1024**2
MAX_FILES = 2048
MAX_WORKING = 256 * 1024**2
MAX_LAYER = 128 * 1024**2
RESERVE = 10 * 1024**3
RUNTIME_PREFIXES = ('server/', 'tools/', 'scripts/', 'static/', 'docs/',
                    'product_docs/', 'web/app/src/', 'skills/')
NON_RUNTIME = ('tests/',)
HOST_ONLY = {'deploy/docker/factortester-server/compose.report-storage.yaml'}
BUILD_INPUTS = {'scripts/server/public_python_dependencies.py'}


def _run(args, *, cwd=None, input=None, timeout=60, env=None):
    return subprocess.run(args, cwd=cwd, input=input, capture_output=True,
                          check=True, timeout=timeout, env=env)


def _git(source, *args, maximum_bytes=2*1024**2):
    # A Docker operator may differ from the release checkout owner. Trust only
    # this explicitly supplied, clean release; never a global safe.directory.
    env={key:value for key,value in os.environ.items() if key not in {
        'GIT_DIR','GIT_WORK_TREE','GIT_INDEX_FILE','GIT_COMMON_DIR',
        'GIT_OBJECT_DIRECTORY','GIT_ALTERNATE_OBJECT_DIRECTORIES','GIT_EXTERNAL_DIFF'}}
    env['GIT_OPTIONAL_LOCKS']='0'
    command=['git', '--no-replace-objects', '-c', 'core.fsmonitor=false',
             '-c', 'core.hooksPath=/dev/null', '-c', 'safe.directory=' + str(source),
             '-C', str(source), *args]
    process=subprocess.Popen(command,env=env,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    output=bytearray();deadline=time.monotonic()+30
    try:
        while True:
            remaining=deadline-time.monotonic()
            if remaining<=0 or not select.select([process.stdout],[],[],remaining)[0]:
                raise TimeoutError('candidate Git read exceeded its deadline')
            chunk=os.read(process.stdout.fileno(),min(65536,maximum_bytes-len(output)+1))
            if not chunk:break
            output.extend(chunk)
            if len(output)>maximum_bytes:raise ValueError('candidate Git output exceeds its byte budget')
        if process.wait(timeout=max(0.1,deadline-time.monotonic())):
            raise ValueError('candidate Git read failed')
        return bytes(output)
    finally:
        if process.poll() is None:process.kill();process.wait(timeout=5)
        process.stdout.close()


def valid_path(value):
    p = PurePosixPath(value)
    if (not value or p.is_absolute() or str(p) != value
            or any(part in {'.', '..', '.git'} for part in p.parts)
            or '\\' in value or '\x00' in value):
        raise ValueError('invalid application patch path')
    return value


def plan_changes(source, base_revision, revision):
    source = Path(source).resolve()
    if any(not re.fullmatch('[0-9a-f]{40}', value) for value in (base_revision, revision)):
        raise ValueError('full immutable source identities are required')
    if _git(source, 'rev-parse', 'HEAD').decode().strip() != revision or _git(source, 'status', '--porcelain').strip():
        raise ValueError('incremental image requires the exact clean candidate checkout')
    raw = _git(source, 'diff', '--no-ext-diff', '--raw', '--no-abbrev', '--no-renames', '-z', base_revision, revision)
    fields = raw.split(b'\x00'); items = []; total = 0
    for offset in range(0, len(fields) - 1, 2):
        metadata, filename = fields[offset], fields[offset + 1]
        path = valid_path(filename.decode())
        if path in BUILD_INPUTS:
            raise ValueError('changed dependency installer requires a normal build')
        parts = metadata.decode().split(); old_mode, new_mode = parts[0][1:], parts[1]
        status, old_id, new_id = parts[-1], parts[2], parts[3]
        if status not in {'A', 'M', 'D'} or any(mode not in {'000000', '100644', '100755'} for mode in (old_mode, new_mode)):
            raise ValueError('incremental image cannot change links, submodules or file types')
        if path.startswith(NON_RUNTIME) or path in HOST_ONLY:
            continue
        if not path.startswith(RUNTIME_PREFIXES):
            raise ValueError('changed build/runtime input requires a normal build: ' + path)
        if len(items)>=MAX_FILES:
            raise ValueError('application patch has too many files')
        record = {'path': path, 'status': status, 'old_oid': old_id, 'new_oid': new_id}
        for prefix, oid, mode in [('old', old_id, old_mode), ('new', new_id, new_mode)]:
            if mode == '000000':
                record[prefix + '_sha256'] = None; record[prefix + '_size'] = 0
                continue
            size = int(_git(source, 'cat-file', '-s', oid))
            if not 0 <= size <= MAX_FILE:
                raise ValueError('application patch file exceeds its limit')
            content = _git(source, 'cat-file', 'blob', oid,maximum_bytes=MAX_FILE)
            if len(content) != size:
                raise ValueError('application patch blob size differs')
            record[prefix + '_sha256'] = hashlib.sha256(content).hexdigest()
            record[prefix + '_size'] = size
        total += record['new_size']
        if total > MAX_PATCH:
            raise ValueError('application patch exceeds its byte budget')
        items.append(record)
    return {'schema_version': 1, 'base_revision': base_revision, 'revision': revision,
            'tree': _git(source, 'rev-parse', revision + '^{tree}').decode().strip(),
            'patch_bytes': total, 'files': items}


# Executed in a fresh, network-isolated container. It compiles source as data;
# it never imports the application, a factor family or the native extension.
_CHECK = r'''
import hashlib,json,pathlib,sys,site
m=json.load(sys.stdin);root=pathlib.Path('/opt/factortester/app')
assert (root/'.deployment-revision').read_text().strip()==m['base_revision']
for item in m['files']:
 p=root/item['path'];assert p.resolve().is_relative_to(root) and not p.is_symlink()
 if item['old_sha256'] is None:assert not p.exists()
 else:
  assert p.is_file() and p.stat().st_size==item['old_size']
  with p.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==item['old_sha256']
for item in m.get('cli_bytecode',[]):
 p=(pathlib.Path('/usr/local/lib/traderesearch-cli')/item['path']).with_suffix('.pyc')
 assert p.is_file() and p.stat().st_size<8*1024**2 and not p.is_symlink()
 with p.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==item['sha256']
paths=[p for directory in site.getsitepackages() for p in (pathlib.Path(directory)/'nautilus_trader').glob('_libnautilus*.so')]
assert len(paths)==1
with paths[0].open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==m['native_sha256']
print('base application and native bytes verified')
'''
_APPLY = r'''
import hashlib,json,marshal,pathlib,py_compile,sys,importlib.util
m=json.load(sys.stdin);root=pathlib.Path('/opt/factortester/app');cli=pathlib.Path('/usr/local/lib/traderesearch-cli');dirs=set();compiled=[];compiled_bytes=0
def writable_parents(p,limit):
 assert p.resolve().is_relative_to(limit) and not p.is_symlink()
 parents=[directory for directory in p.parents if directory.is_relative_to(limit)]
 for directory in reversed(parents):
  assert not directory.is_symlink();directory.mkdir(parents=True,exist_ok=True);directory.chmod(0o755);dirs.add(directory)
for item in m['files']:
 p=root/item['path'];writable_parents(p,root)
 if item['status']=='D':p.unlink()
 else:
  assert p.is_file() and p.stat().st_size==item['new_size']
  with p.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==item['new_sha256']
  p.chmod(0o444)
 if item['path'].startswith('tools/cli/') and item['path'].endswith('.py'):
  target=(cli/item['path']).with_suffix('.pyc');writable_parents(target,cli)
  if item['status']=='D':target.unlink(missing_ok=True)
  else:
   filename='/runtime/'+item['path']
   py_compile.compile(str(p),cfile=str(target),dfile=filename,doraise=True,optimize=0,invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH)
   assert target.stat().st_size<8*1024**2
   raw=target.read_bytes();compiled_bytes+=len(raw);assert compiled_bytes<=32*1024**2 and raw[:4]==importlib.util.MAGIC_NUMBER
   assert marshal.loads(raw[16:])==compile(p.read_bytes(),filename,'exec',dont_inherit=True,optimize=0)
   target.chmod(0o444);compiled.append({'path':item['path'],'sha256':hashlib.sha256(raw).hexdigest()})
marker=root/'.deployment-revision';writable_parents(marker,root);marker.chmod(0o644);marker.write_text(m['revision']+'\n');marker.chmod(0o444)
m['cli_bytecode']=compiled
raw=json.dumps(m,sort_keys=True,separators=(',',':')).encode();receipt=root/'.incremental-source.json'
if receipt.exists():receipt.chmod(0o644)
receipt.write_bytes(raw);receipt.chmod(0o444)
for directory in dirs:directory.chmod(0o555)
print(json.dumps({'manifest_sha256':hashlib.sha256(raw).hexdigest(),'cli_files':len(compiled),'cli_bytecode':compiled}))
'''


def _inspect(image):
    values = json.loads(_run(['docker', 'image', 'inspect', image]).stdout)
    if not isinstance(values, list) or len(values) != 1:
        raise ValueError('ambiguous immutable image')
    return values[0]


def require_resource_controls(info, *, meminfo=Path('/proc/meminfo')):
    if info.get('OSType')!='linux' or any(info.get(key) is not True for key in (
            'MemoryLimit','SwapLimit','CpuCfsQuota','PidsLimit')):
        raise ValueError('incremental assembly requires effective Linux resource controls')
    available=next((int(line.split()[1])*1024 for line in meminfo.read_text().splitlines()
                    if line.startswith('MemAvailable:')),0)
    if available<1024**3:
        raise ValueError('incremental assembly requires 1 GiB available RAM, excluding swap')


def assemble(source, plan, *, base_image, image, native_sha256, work_root):
    started=time.monotonic()
    if os.environ.get('FACTORTESTER_PUBLISH_AUTHORIZED') != '1':
        raise PermissionError('explicit release authorization is required')
    if not image.endswith(':' + plan['revision']) or any(c.isspace() for c in image) or image.startswith('-'):
        raise ValueError('candidate image must use its immutable source revision')
    # Never replace an existing SHA tag or remove a historical image.
    probe = subprocess.run(['docker', 'image', 'inspect', image], capture_output=True)
    if probe.returncode == 0:
        raise ValueError('candidate image already exists; verify it through the regular release entrypoint')
    if not any(message in probe.stderr.decode().lower() for message in ('no such image', 'no such object')):
        raise RuntimeError('candidate image inventory could not be verified')
    base = _inspect(base_image);config=base['Config'];labels=config.get('Labels') or {}
    if (labels.get('org.opencontainers.image.revision') != plan['base_revision']
            or not labels.get('org.traderesearch.python-deps.identity')
            or not labels.get('org.traderesearch.nautilus.revision')
            or config.get('User', '') not in {'', '0', 'root'} or config.get('Volumes')):
        raise ValueError('base runtime is not eligible for an app-only layer')
    plan = {**plan, 'base_image_id': base['Id'], 'native_sha256': native_sha256}
    work_root = Path(work_root);work_root.mkdir(parents=True,exist_ok=True)
    info=json.loads(_run(['docker','info','--format','{{json .}}']).stdout)
    require_resource_controls(info)
    docker_root=Path(info['DockerRootDir'])
    if not docker_root.is_absolute() or not docker_root.is_dir():
        raise ValueError('incremental assembly must run on the actual Docker host')
    filesystems={path.stat().st_dev:path for path in (work_root,docker_root)}
    initial={device:shutil.disk_usage(path).free for device,path in filesystems.items()}
    if any(free < RESERVE + MAX_WORKING for free in initial.values()):
        raise ValueError('insufficient incremental workspace headroom')
    def guard():
        for device,path in filesystems.items():
            free = shutil.disk_usage(path).free
            if free < RESERVE or initial[device]-free > MAX_WORKING:
                raise RuntimeError('incremental image exceeded its storage budget')
    container = None;created_image=None;confirmed=False
    with tempfile.TemporaryDirectory(prefix='tr-app-layer-',dir=work_root) as temporary:
        payload = Path(temporary)/'payload';payload.mkdir()
        for item in plan['files']:
            if item['status'] == 'D':continue
            target=payload/item['path'];target.parent.mkdir(parents=True,exist_ok=True)
            raw=_git(source,'cat-file','blob',item['new_oid'],maximum_bytes=MAX_FILE)
            if len(raw)!=item['new_size'] or hashlib.sha256(raw).hexdigest()!=item['new_sha256']:
                raise ValueError('candidate source changed while preparing application bytes')
            target.write_bytes(raw)
        try:
            container=_run(['docker','create','--network','none','--memory','512m','--memory-swap','512m',
                '--cpus','1','--pids-limit','64','--cap-drop','ALL','--security-opt','no-new-privileges:true',
                '--user','0','--entrypoint','sleep',base['Id'],'300']).stdout.decode().strip()
            if not re.fullmatch('[0-9a-f]{64}',container):
                raise ValueError('temporary container has no immutable identity')
            setup=json.loads(_run(['docker','inspect',container]).stdout)[0]
            limits=setup['HostConfig']
            if (setup.get('Mounts') or limits['NetworkMode']!='none' or limits['Privileged']
                    or limits['Memory']!=512*1024**2 or limits['MemorySwap']!=512*1024**2
                    or limits['NanoCpus']!=10**9 or limits['PidsLimit']!=64):
                raise ValueError('temporary assembly resource isolation differs')
            _run(['docker','start',container]);encoded=json.dumps(plan).encode()
            _run(['docker','exec','-i',container,'python','-c',_CHECK],input=encoded)
            guard();_run(['docker','cp',str(payload)+'/.',container+':/opt/factortester/app/'])
            applied=json.loads(_run(['docker','exec','-i',container,'python','-c',_APPLY],input=encoded).stdout)
            guard()
            for args in (['--help'],['research','--help']):
                result=_run(['docker','exec',container,'/usr/local/bin/traderesearch',*args])
                if not result.stdout:raise ValueError('candidate CLI did not expose its command surface')
            final_check={**plan,'base_revision':plan['revision'],'cli_bytecode':applied['cli_bytecode'],
                'files':[{**item,'old_sha256':item['new_sha256'],'old_size':item['new_size']} for item in plan['files']]}
            _run(['docker','exec','-i',container,'python','-c',_CHECK],input=json.dumps(final_check).encode())
            peak=subprocess.run(['docker','exec',container,'cat','/sys/fs/cgroup/memory.peak'],capture_output=True,timeout=10)
            peak_bytes=int(peak.stdout.strip()) if peak.returncode==0 and peak.stdout.strip().isdigit() else None
            _run(['docker','stop','--time','1',container]);guard()
            changes=['ENTRYPOINT '+json.dumps(config.get('Entrypoint') or []),
                     'CMD '+json.dumps(config.get('Cmd') or []),'USER '+(config.get('User') or 'root'),
                     'LABEL org.opencontainers.image.revision='+plan['revision'],
                     'LABEL org.traderesearch.incremental.base='+base['Id'],
                     'LABEL org.traderesearch.incremental.manifest='+applied['manifest_sha256']]
            command=['docker','commit']
            for change in changes:command.extend(['--change',change])
            created_image=_run([*command,container,image],timeout=60).stdout.decode().strip();guard()
            candidate=_inspect(image);old_layers=base['RootFS']['Layers'];new_layers=candidate['RootFS']['Layers']
            if (new_layers[:len(old_layers)]!=old_layers or len(new_layers)!=len(old_layers)+1
                    or candidate['Size']-base['Size']>MAX_LAYER
                    or candidate['Config']['Entrypoint']!=config['Entrypoint']
                    or (candidate['Config'].get('Cmd') or [])!=(config.get('Cmd') or [])):
                raise ValueError('candidate does not preserve the complete frozen runtime')
            confirmed=True
            return {'revision':plan['revision'],'base_image_id':base['Id'],'image_id':candidate['Id'],
                    'shared_layers':len(old_layers),'added_layers':1,'added_image_bytes':candidate['Size']-base['Size'],
                    'patch_bytes':plan['patch_bytes'],'cli_files':applied['cli_files'],
                    'native_sha256':native_sha256,'manifest_sha256':applied['manifest_sha256'],
                    'wheel_builds':0,'dependency_installs':0,'native_builds':0,
                    'assembly_cgroup_peak_bytes':peak_bytes,'elapsed_seconds':time.monotonic()-started}
        finally:
            if container is not None:
                subprocess.run(['docker','rm','--force',container],capture_output=True,timeout=30)
            if created_image is not None and not confirmed:
                # Only our unused failed candidate can be removed. Never prune
                # a prior release, a base layer or another concurrent tag.
                current=subprocess.run(['docker','image','inspect','--format','{{.Id}}',image],capture_output=True)
                if current.returncode==0 and current.stdout.decode().strip()==created_image:
                    subprocess.run(['docker','image','rm',image],capture_output=True,timeout=30)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--base-revision',required=True)
    parser.add_argument('--revision',required=True)
    parser.add_argument('--base-image',required=True)
    parser.add_argument('--image',required=True)
    parser.add_argument('--native-sha256',required=True)
    parser.add_argument('--work-root',type=Path,required=True)
    parser.add_argument('--lock-file',type=Path,required=True)
    parser.add_argument('--build',action='store_true')
    args=parser.parse_args()
    if (not re.fullmatch('[0-9a-f]{40}',args.revision) or not re.fullmatch('[0-9a-f]{40}',args.base_revision)
            or not re.fullmatch('[0-9a-f]{64}',args.native_sha256)):
        parser.error('immutable source and native identities are required')
    plan=plan_changes(args.source,args.base_revision,args.revision)
    if not args.build:
        print(json.dumps(plan));return
    if os.environ.get('FACTORTESTER_PUBLISH_AUTHORIZED')!='1':
        parser.error('explicit release authorization is required before assembly')
    import fcntl
    with args.lock_file.open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        receipt=assemble(args.source,plan,base_image=args.base_image,image=args.image,
                         native_sha256=args.native_sha256,work_root=args.work_root)
        print(json.dumps(receipt))


if __name__=='__main__':
    main()
