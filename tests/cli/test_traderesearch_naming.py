"""Canonical CLI names share config, cookies and the verified release runtime."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner
from tools.cli import http


@pytest.fixture(autouse=True)
def isolated_names(monkeypatch):
    for prefix in ('TRADERESEARCH_', 'FACTORTESTER_'):
        for name in ('CONFIG', 'HOME', 'STREAM_TIMEOUT', 'MANAGER_CONFIG', 'MANAGER_TOKEN'):
            monkeypatch.delenv(prefix + name, raising=False)


def test_canonical_help_and_welcome():
    from tools.cli.app import cli
    from tools.cli.manager_app import manager_cli
    from tools.cli.core.display import print_home_welcome
    for command in (cli, manager_cli):
        result = CliRunner().invoke(command, ['--help'])
        assert result.exit_code == 0, result.output
        assert 'TradeResearch' in result.output and 'FactorTester' not in result.output
    cli_help = CliRunner().invoke(cli, ['--help']).output
    assert 'traderesearch configure' in cli_help
    assert 'factortester configure' not in cli_help
    with CliRunner().isolation() as streams:
        print_home_welcome()
        assert b'TradeResearch CLI' in streams[0].getvalue()


def test_canonical_environment_selects_one_state_authority(monkeypatch, tmp_path):
    legacy = tmp_path / 'old'; canonical = tmp_path / 'new'
    monkeypatch.setenv('FACTORTESTER_HOME', str(legacy))
    assert http.cookie_path() == legacy / 'cookies.lwp'
    monkeypatch.setenv('TRADERESEARCH_HOME', str(canonical))
    assert http.cookie_path() == canonical / 'cookies.lwp'
    assert http.state_path() == canonical / 'state.json'
    old_config = legacy / 'explicit.json'
    new_config = canonical / 'explicit.json'
    monkeypatch.setenv('FACTORTESTER_CONFIG', str(old_config))
    monkeypatch.setenv('TRADERESEARCH_CONFIG', str(new_config))
    http.save_config(http.ClientConfig('https://manager.example:7998'))
    assert http.config_path() == new_config
    assert http.load_config().base_url == 'https://manager.example:7998'
    assert not legacy.exists()
    assert http.cookie_path_for('https://manager.example:7998').parent == canonical / 'cookies'
    assert http.native_selection_path() == canonical / 'explicit.native.json'


def test_existing_credentials_are_not_moved_or_copied(monkeypatch, tmp_path):
    monkeypatch.setattr(http, 'DEFAULT_HOME', tmp_path / '.factortester')
    home = http.DEFAULT_HOME; home.mkdir()
    path = home / 'cookies.lwp'; path.write_text('old cookie state')
    before = path.stat().st_ino
    assert http.cookie_path() == path and path.stat().st_ino == before
    assert not (tmp_path / '.traderesearch').exists()
    with pytest.raises(FileNotFoundError, match='TradeResearch.*traderesearch configure'):
        http.load_config()


def test_stream_timeout_new_name_has_precedence(monkeypatch):
    session = SimpleNamespace(timeout=30)
    monkeypatch.setenv('FACTORTESTER_STREAM_TIMEOUT', '100')
    assert http.HttpSession._stream_timeout(session) == 100
    monkeypatch.setenv('TRADERESEARCH_STREAM_TIMEOUT', '200')
    assert http.HttpSession._stream_timeout(session) == 200
    monkeypatch.setenv('TRADERESEARCH_STREAM_TIMEOUT', 'invalid')
    assert http.HttpSession._stream_timeout(session) == http.DEFAULT_STREAM_TIMEOUT


def test_canonical_stable_launchers_reuse_single_verified_runtime(tmp_path):
    from tools.cli.release.materialize import install_stable_launchers, stable_launchers_are_current
    import json, subprocess
    root = tmp_path / 'client'
    root.mkdir(); (root / 'current.json').write_text(json.dumps({'version': '1.2.3'}))
    runtime = root / 'releases/1.2.3/runtime/standalone/bin'
    runtime.mkdir(parents=True)
    for command in ('factortester', 'factortester-manager'):
        script = runtime / command
        script.write_text('#!/bin/sh\nprintf "%s\\n" "$1"\n')
        script.chmod(0o755)
    install_stable_launchers(root)
    assert stable_launchers_are_current(root)
    for command in ('traderesearch', 'traderesearch-manager', 'factortester', 'factortester-manager'):
        result = subprocess.run([str(root / 'bin' / command), 'same-runtime'], capture_output=True, text=True)
        assert result.returncode == 0 and result.stdout.strip() == 'same-runtime'
    assert sorted(path.name for path in runtime.iterdir()) == ['factortester', 'factortester-manager']


def test_manager_reuses_canonical_config_resolver_and_existing_credential_key(monkeypatch,tmp_path):
    from tools.cli.manager import config as manager
    monkeypatch.setenv('TRADERESEARCH_HOME',str(tmp_path))
    assert manager.manager_config_path()==tmp_path/'manager.json'
    monkeypatch.setenv('FACTORTESTER_MANAGER_CONFIG',str(tmp_path/'old.json'))
    monkeypatch.setenv('TRADERESEARCH_MANAGER_CONFIG',str(tmp_path/'new.json'))
    assert manager.manager_config_path()==tmp_path/'new.json'
    monkeypatch.setenv('FACTORTESTER_MANAGER_TOKEN','legacy-fixture')
    monkeypatch.setenv('TRADERESEARCH_MANAGER_TOKEN','canonical-fixture')
    store=manager.ManagerCredentialStore(manager.ManagerConfig('https://manager.example:7998'))
    assert store.read()=='canonical-fixture'
    monkeypatch.delenv('TRADERESEARCH_MANAGER_TOKEN')
    assert store.read()=='legacy-fixture'
    assert manager.KEYCHAIN_SERVICE=='com.gtht.factortester.manager'


def test_release_builder_requests_canonical_distribution(monkeypatch,tmp_path):
    from scripts.release import assets
    calls=[]
    wheel=tmp_path/'traderesearch-0.1.2-py3-none-any.whl'
    monkeypatch.setattr(assets,'_build_wheel',lambda source,name,out:calls.append((source,name,out)) or wheel)
    monkeypatch.setattr(assets.subprocess,'run',lambda *a,**kw:None)
    assert assets.build_python_assets(tmp_path/'repo',tmp_path)==[wheel]
    assert calls==[(tmp_path/'repo/tools/cli','traderesearch',tmp_path)]
