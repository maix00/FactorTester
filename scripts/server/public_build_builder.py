#!/usr/bin/env python3
"""Prepare and verify a bounded Docker-native builder before public builds."""
from __future__ import annotations
import json
import re
from pathlib import Path
import subprocess

NAME = 'tr-public-bounded'
MEMORY = 2 * 1024**3
RESERVE = 512 * 1024**2


def validate_limits(value: dict) -> None:
    host = value['HostConfig']
    if (host.get('Memory') != MEMORY or host.get('MemorySwap') != MEMORY
            or host.get('CpuPeriod') != 100000 or host.get('CpuQuota') != 200000):
        raise RuntimeError('public builder must enforce 2 GiB without swap and two CPU cores')


def require_host_headroom(meminfo: Path = Path('/proc/meminfo')) -> None:
    # The public build runs on its Linux Docker host. macOS local validation
    # has no /proc; Docker Desktop still enforces the verified cgroup limits.
    if not meminfo.exists():
        return
    available = next((int(line.split()[1]) * 1024
                      for line in meminfo.read_text().splitlines()
                      if line.startswith('MemAvailable:')), None)
    if available is None or available < MEMORY + RESERVE:
        raise RuntimeError('public build needs 2.5 GiB available RAM; existing services stay running')


def prepare(run=subprocess.run) -> str:
    def call(args, *, check=True):
        return run(['docker', *args], capture_output=True, text=True, check=check, timeout=180)
    call(['info', '--format', '{{.ServerVersion}}'])
    require_host_headroom()
    found = call(['buildx', 'inspect', NAME], check=False)
    if found.returncode:
        # Never interpret a daemon/network failure as permission to replace state.
        if 'no builder' not in found.stderr.lower() and 'not found' not in found.stderr.lower():
            raise RuntimeError('cannot inspect bounded public builder')
        call(['buildx', 'create', '--name', NAME, '--driver', 'docker-container',
              '--driver-opt', 'memory=2g', '--driver-opt', 'memory-swap=2g',
              '--driver-opt', 'cpu-period=100000', '--driver-opt', 'cpu-quota=200000',
              '--driver-opt', 'default-load=true',
              '--buildkitd-config', str(Path(__file__).with_name('public-buildkit.toml'))])
    else:
        driver = re.search(r'^Driver:\s*(\S+)\s*$', found.stdout, re.MULTILINE)
        if not driver or driver.group(1) != 'docker-container':
            raise RuntimeError('refusing an unbounded public build driver')
    call(['buildx', 'inspect', NAME, '--bootstrap'])
    inspected = call(['inspect', 'buildx_buildkit_' + NAME + '0'])
    validate_limits(json.loads(inspected.stdout)[0])
    return NAME


if __name__ == '__main__':
    print(prepare())
