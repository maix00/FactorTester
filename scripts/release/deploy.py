"""Plan optional server/macOS/iOS stages; execution is explicit and sequential."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
GIB = 1024**3


def plan(args, root=ROOT):
    stages = []
    def add(name, command, cwd=root, env=None):
        stages.append(dict(stage=name, command=[str(x) for x in command], cwd=str(cwd), env=env or {}))
    if args.server != 'none':
        if args.server == 'public':
            add('public-server', ['bash', root/'scripts/server/publish_public_main.sh'])
        else:
            if not args.intranet_env:
                raise ValueError('--intranet-env is required for the selected intranet deployment')
            add('intranet-manager', ['bash', root/'scripts/server/factortester_container.sh', 'manager-reload'],
                env={'FACTORTESTER_DOCKER_ENV_FILE':str(Path(args.intranet_env).expanduser().resolve())})
    if args.macos != 'none':
        add('macos-'+args.macos, ['bash', root/'scripts/build_and_run.sh', 'build' if args.macos == 'build' else '--install'])
    if args.ios != 'none':
        device = args.ios_target == 'device'
        if args.ios == 'install' and not args.device_id:
            raise ValueError('iOS installation requires an explicit --device-id')
        if device and args.ios == 'install' and not args.team_id:
            raise ValueError('signed device installation requires --team-id')
        destination = ('id='+args.device_id) if args.device_id else ('generic/platform=iOS' + ('' if device else ' Simulator'))
        derived = root/'apple'/('build-ios-device' if device else 'build-ios-simulator')
        add('ios-project', ['xcodegen','generate','--spec',root/'apple/project.yml','--project',root/'apple'])
        command=['xcodebuild','-project',root/'apple/FactorTester-Client.xcodeproj',
                 '-scheme','FactorTester-Client-iOS-UI','-configuration','Debug',
                 '-derivedDataPath',derived,'-destination',destination,'-jobs','2','build']
        command += ['DEVELOPMENT_TEAM='+args.team_id] if device and args.team_id else ['CODE_SIGNING_ALLOWED=NO']
        add('ios-build',command)
        if args.ios == 'install':
            app=derived/'Build/Products'/('Debug-iphoneos' if device else 'Debug-iphonesimulator')/'TradeResearch.app'
            command=(['xcrun','devicectl','device','install','app','--device',args.device_id,app] if device
                     else ['xcrun','simctl','install',args.device_id,app])
            add('ios-install',command)
    return stages


def check_storage(args, root=ROOT):
    if shutil.disk_usage(root).free < args.min_free_gib * GIB:
        raise ValueError('insufficient free storage; no further stages executed')
    size=0
    for name in ('build','build-ios-device','build-ios-simulator'):
        path=root/'apple'/name
        if path.exists():
            size+=int(subprocess.check_output(['du','-sk',str(path)],text=True).split()[0])*1024
    if size > args.max_client_cache_gib*GIB:
        raise ValueError('combined client caches exceed budget; preserve and review before cleanup')


def preflight(args, stages, root=ROOT):
    check_storage(args, root)
    if args.server != 'none':
        branch=subprocess.check_output(['git','branch','--show-current'],cwd=root,text=True).strip()
        expected='main' if args.server=='public' else 'feat'
        if branch!=expected or subprocess.check_output(['git','status','--porcelain'],cwd=root,text=True).strip():
            raise ValueError(f'server deployment requires a clean {expected} checkout')
        if args.server=='public' and os.environ.get('FACTORTESTER_PUBLISH_AUTHORIZED')!='1':
            raise ValueError('public publication requires explicit release authorization')
    if args.ios=='install' and args.ios_target=='simulator':
        devices=json.loads(subprocess.check_output(['xcrun','simctl','list','devices','--json'],text=True))
        if not any(d.get('udid')==args.device_id and d.get('state')=='Booted'
                   for group in devices['devices'].values() for d in group):
            raise ValueError('selected simulator must already be booted; no device was started')
    for stage in stages:
        if not shutil.which(stage['command'][0]):
            raise ValueError('missing executable: '+stage['command'][0])


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--server',choices=['none','intranet','public'],default='none')
    p.add_argument('--intranet-env')
    p.add_argument('--macos',choices=['none','build','install'],default='none')
    p.add_argument('--ios',choices=['none','build','install'],default='none')
    p.add_argument('--ios-target',choices=['simulator','device'],default='simulator')
    p.add_argument('--device-id')
    p.add_argument('--team-id')
    p.add_argument('--min-free-gib',type=int,default=15)
    p.add_argument('--max-client-cache-gib',type=int,default=12)
    p.add_argument('--execute',action='store_true')
    args=p.parse_args(argv)
    try:
        if min(args.min_free_gib,args.max_client_cache_gib)<=0:
            raise ValueError('storage budgets must be positive')
        stages=plan(args)
        print(json.dumps({'execute':args.execute,'stages':stages},indent=2),flush=True)
        if args.execute:
            preflight(args,stages)
            for stage in stages:
                subprocess.run(stage['command'],cwd=stage['cwd'],env={**os.environ,**stage['env']},check=True)
                check_storage(args)
    except (ValueError,OSError,subprocess.SubprocessError) as e:
        p.exit(2,str(e)+'\n')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
