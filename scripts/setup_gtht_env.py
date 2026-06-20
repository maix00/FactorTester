#!/usr/bin/env python3
"""Create or update a named FactorTester conda environment."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


DEFAULT_ENV_NAME = 'GTHT'
REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = REPO_ROOT / 'environment.yml'


def _run(command: list[str]) -> None:
    print('+', ' '.join(command), flush=True)
    subprocess.run(command, cwd=REPO_ROOT, check=True)


def _environment_exists(env_name: str) -> bool:
    result = subprocess.run(
        ['conda', 'env', 'list', '--json'],
        check=True,
        capture_output=True,
        text=True,
    )
    environments = json.loads(result.stdout).get('envs', [])
    return any(Path(prefix).name == env_name for prefix in environments)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--name',
        default=os.environ.get('GTHT_CONDA_ENV', DEFAULT_ENV_NAME),
        help='Conda environment name (default: GTHT or GTHT_CONDA_ENV).',
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    env_name = _parse_args(argv).name.strip()
    if not env_name:
        raise ValueError('Conda environment name cannot be empty')
    action = 'update' if _environment_exists(env_name) else 'create'
    env_command = ['conda', 'env', action, '-n', env_name, '-f', str(ENV_FILE)]
    if action == 'create':
        env_command.append('-y')
    _run(env_command)

    if sys.platform == 'win32':
        _run([
            'conda', 'install', '-n', env_name, '-c', 'conda-forge',
            'blas=*=*mkl', 'numpy==2.3.4', 'scipy==1.16.3', '-y',
        ])
    elif sys.platform == 'darwin':
        # An existing conda NumPy has matching version metadata, so pip would
        # otherwise keep its OpenBLAS build instead of installing Accelerate.
        _run([
            'conda', 'run', '-n', env_name, 'python', '-m', 'pip', 'install',
            '--force-reinstall', '--no-deps', 'numpy==2.3.4', 'scipy==1.16.3',
        ])

    _run([
        'conda', 'run', '-n', env_name, 'python', '-c',
        "import numpy as np; print('NumPy BLAS:', np.__config__.CONFIG['Build Dependencies']['blas']['name'])",
    ])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
