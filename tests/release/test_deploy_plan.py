from argparse import Namespace
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest
from scripts.release import deploy


def args(**changes):
    values=dict(server='none',intranet_env=None,macos='none',ios='none',ios_target='simulator',
                device_id=None,team_id=None,min_free_gib=15,max_client_cache_gib=12)
    return Namespace(**(values|changes))


def test_default_and_explicit_client_plans_do_not_execute(tmp_path):
    with patch.object(deploy.subprocess,'run',side_effect=AssertionError('unexpected execution')):
        assert deploy.main([])==0
        assert deploy.main(['--macos','build','--ios','build'])==0
    assert deploy.plan(args())==[]
    stages=deploy.plan(args(macos='build',ios='build'),tmp_path)
    assert all(stage['stage']!='public-server' for stage in stages)
    assert not any('install' in stage['stage'] for stage in stages)


def test_install_requires_named_device_and_real_device_signing():
    with pytest.raises(ValueError,match='device-id'):
        deploy.plan(args(ios='install'))
    with pytest.raises(ValueError,match='team-id'):
        deploy.plan(args(ios='install',ios_target='device',device_id='real-device'))


def test_unbooted_simulator_is_rejected_before_any_install(tmp_path):
    options=args(ios='install',device_id='chosen')
    with patch.object(deploy,'check_storage'), patch.object(deploy.subprocess,'check_output',return_value=json.dumps({'devices':{'runtime':[{'udid':'chosen','state':'Shutdown'}]}})):
        with pytest.raises(ValueError,match='already be booted'):
            deploy.preflight(options,deploy.plan(options,tmp_path),tmp_path)


def test_low_storage_prevents_execution(tmp_path):
    with patch.object(deploy.shutil,'disk_usage',return_value=Namespace(free=1024)):
        with pytest.raises(ValueError,match='insufficient free storage'):
            deploy.preflight(args(macos='install'),[],tmp_path)


def test_client_storage_budget_is_combined(tmp_path):
    for name in ('build','build-ios-simulator'):
        (tmp_path/'apple'/name).mkdir(parents=True)
    with patch.object(deploy.shutil,'disk_usage',return_value=Namespace(free=100*deploy.GIB)), patch.object(deploy.subprocess,'check_output',return_value=str(7*1024**2)+' cache'):
        with pytest.raises(ValueError,match='combined'):
            deploy.check_storage(args(),tmp_path)


def test_invalid_macos_mode_stops_before_tools_are_called(tmp_path):
    root=Path(__file__).resolve().parents[2]
    result=subprocess.run(['bash',str(root/'scripts/build_and_run.sh'),'unsupported'],capture_output=True,text=True)
    assert result.returncode==2
    assert 'usage:' in result.stderr
    assert not result.stdout
