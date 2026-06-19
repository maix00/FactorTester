#!/usr/bin/env python3
"""Create or update the GTHT conda environment with platform tuning."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ENV_NAME = 'GTHT'
REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = REPO_ROOT / 'environment.yml'


def _run(command: list[str]) -> None:
    print('+', ' '.join(command), flush=True)
    subprocess.run(command, cwd=REPO_ROOT, check=True)


def _environment_exists() -> bool:
    result = subprocess.run(
        ['conda', 'env', 'list', '--json'],
        check=True,
        capture_output=True,
        text=True,
    )
    environments = json.loads(result.stdout).get('envs', [])
    return any(Path(prefix).name == ENV_NAME for prefix in environments)


def main() -> int:
    action = 'update' if _environment_exists() else 'create'
    env_command = ['conda', 'env', action, '-n', ENV_NAME, '-f', str(ENV_FILE)]
    if action == 'create':
        env_command.append('-y')
    _run(env_command)

    if sys.platform == 'win32':
        _run([
            'conda', 'install', '-n', ENV_NAME, '-c', 'conda-forge',
            'blas=*=*mkl', 'numpy==2.3.4', 'scipy==1.16.3', '-y',
        ])
    elif sys.platform == 'darwin':
        # An existing conda NumPy has matching version metadata, so pip would
        # otherwise keep its OpenBLAS build instead of installing Accelerate.
        _run([
            'conda', 'run', '-n', ENV_NAME, 'python', '-m', 'pip', 'install',
            '--force-reinstall', '--no-deps', 'numpy==2.3.4', 'scipy==1.16.3',
        ])

    _run([
        'conda', 'run', '-n', ENV_NAME, 'python', '-c',
        "import numpy as np; print('NumPy BLAS:', np.__config__.CONFIG['Build Dependencies']['blas']['name'])",
    ])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
