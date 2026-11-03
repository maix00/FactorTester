#!/usr/bin/env python3
"""Prepare and verify a bounded Docker-native builder before public builds."""
from __future__ import annotations
import json
import os
import re
import tempfile
from urllib.parse import urlsplit
from pathlib import Path
import subprocess

NAME = 'tr-public-bounded'
MEMORY = 2 * 1024**3
RESERVE = 512 * 1024**2


def selected_memory() -> int:
    value = os.environ.get('TR_PUBLIC_BUILD_MEMORY_MIB', '2048')
    if value not in {'1536', '2048'}:
        raise ValueError('TR_PUBLIC_BUILD_MEMORY_MIB must be 1536 or 2048')
    return int(value) * 1024**2


def validate_limits(value: dict, *, memory: int = MEMORY) -> None:
    host = value['HostConfig']
    if (host.get('Memory') != memory or host.get('MemorySwap') != memory
            or host.get('CpuPeriod') != 100000 or host.get('CpuQuota') != 200000):
        raise RuntimeError(f'public builder must enforce {memory // 1024**2} MiB without swap and two CPU cores')


def require_host_headroom(meminfo: Path = Path('/proc/meminfo'), *, memory: int = MEMORY) -> None:
    # The public build runs on its Linux Docker host. macOS local validation
    # has no /proc; Docker Desktop still enforces the verified cgroup limits.
    if not meminfo.exists():
        return
    available = next((int(line.split()[1]) * 1024
                      for line in meminfo.read_text().splitlines()
                      if line.startswith('MemAvailable:')), None)
    if available is None or available < memory + RESERVE:
        raise RuntimeError(f'public build needs {(memory + RESERVE) // 1024**2} MiB available RAM; existing services stay running')


def builder_config(mirrors: list[str]) -> str:
    config = Path(__file__).with_name('public-buildkit.toml').read_text()
    hosts = []
    for value in mirrors:
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
                or parsed.password or parsed.path not in {'', '/'}
                or parsed.query or parsed.fragment):
            raise ValueError('public builder requires HTTPS registry mirrors without credentials or paths')
        hosts.append(parsed.netloc)
    if hosts:
        config += '\n[registry."docker.io"]\n  mirrors = ' + json.dumps(hosts) + '\n'
    return config


def prepare(run=subprocess.run, *, headroom=None, memory: int = MEMORY) -> str:
    if memory not in {1536 * 1024**2, MEMORY}:
        raise ValueError('unsupported public build memory budget')
    # A separate profile preserves the existing builder/cache and cannot resize
    # another in-flight build. Capacity admission counts both running builders.
    name = NAME if memory == MEMORY else NAME + '-1536m'
    memory_option = '2g' if memory == MEMORY else '1536m'
    def call(args, *, check=True):
        return run(['docker', *args], capture_output=True, text=True, check=check, timeout=180)
    call(['info', '--format', '{{.ServerVersion}}'])
    if headroom is None:
        require_host_headroom(memory=memory)
    else:
        headroom()
    found = call(['buildx', 'inspect', name], check=False)
    if found.returncode:
        # Never interpret a daemon/network failure as permission to replace state.
        if 'no builder' not in found.stderr.lower() and 'not found' not in found.stderr.lower():
            raise RuntimeError('cannot inspect bounded public builder')
        mirrors = json.loads(call(['info', '--format', '{{json .RegistryConfig.Mirrors}}']).stdout or '[]')
        with tempfile.NamedTemporaryFile('w', suffix='.toml', prefix='tr-buildkit-') as config:
            config.write(builder_config(mirrors)); config.flush()
            call(['buildx', 'create', '--name', name, '--driver', 'docker-container',
                  '--driver-opt', f'memory={memory_option}', '--driver-opt', f'memory-swap={memory_option}',
                  '--driver-opt', 'cpu-period=100000', '--driver-opt', 'cpu-quota=200000',
                  '--buildkitd-config', config.name])
    else:
        driver = re.search(r'^Driver:\s*(\S+)\s*$', found.stdout, re.MULTILINE)
        if not driver or driver.group(1) != 'docker-container':
            raise RuntimeError('refusing an unbounded public build driver')
    call(['buildx', 'inspect', name, '--bootstrap'])
    inspected = call(['inspect', 'buildx_buildkit_' + name + '0'])
    validate_limits(json.loads(inspected.stdout)[0], memory=memory)
    return name


if __name__ == '__main__':
    print(prepare(memory=selected_memory()))
