from __future__ import annotations

from scripts import setup_gtht_env


def test_setup_env_updates_macos_and_forces_accelerate_wheels(monkeypatch):
    commands = []
    monkeypatch.setattr(setup_gtht_env, '_environment_exists', lambda name: True)
    monkeypatch.setattr(setup_gtht_env, '_run', commands.append)
    monkeypatch.setattr(setup_gtht_env.sys, 'platform', 'darwin')

    assert setup_gtht_env.main(['--name', 'research-mac']) == 0

    assert commands[0][:4] == ['conda', 'env', 'update', '-n']
    assert commands[0][4] == 'research-mac'
    assert '-y' not in commands[0]
    assert commands[1][-3:] == ['--no-deps', 'numpy==2.3.4', 'scipy==1.16.3']
    assert '--force-reinstall' in commands[1]


def test_setup_env_creates_windows_environment_and_switches_to_mkl(monkeypatch):
    commands = []
    monkeypatch.setattr(setup_gtht_env, '_environment_exists', lambda name: False)
    monkeypatch.setattr(setup_gtht_env, '_run', commands.append)
    monkeypatch.setattr(setup_gtht_env.sys, 'platform', 'win32')

    assert setup_gtht_env.main(['--name', 'research-win']) == 0

    assert commands[0][:4] == ['conda', 'env', 'create', '-n']
    assert commands[0][-1] == '-y'
    assert commands[1] == [
        'conda', 'install', '-n', 'research-win', '-c', 'conda-forge',
        'blas=*=*mkl', 'numpy==2.3.4', 'scipy==1.16.3', '-y',
    ]
