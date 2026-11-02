import json
import os
from pathlib import Path
import subprocess


SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/server/test_nautilus_wheel.sh'


def test_smoke_requires_an_explicit_image_and_never_starts_manager(tmp_path):
    wheel = tmp_path / 'selected.whl'
    wheel.touch()
    env = {k: v for k, v in os.environ.items() if k != 'FACTORTESTER_IMAGE'}
    rejected = subprocess.run(['bash', str(SCRIPT), str(wheel)], env=env, capture_output=True, text=True)
    assert rejected.returncode != 0 and 'reviewed runtime image' in rejected.stderr
    docker = tmp_path / 'docker'
    docker.write_text('#!/usr/bin/env python3\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n')
    docker.chmod(0o700)
    env.update(PATH=str(tmp_path)+os.pathsep+env['PATH'], FACTORTESTER_IMAGE='reviewed:exact-revision')
    result = subprocess.run(['bash', str(SCRIPT), str(wheel)], env=env, capture_output=True, text=True, check=True)
    args = json.loads(result.stdout)
    for flag, value in [('--network', 'none'), ('--entrypoint', 'bash'), ('--platform', 'linux/amd64')]:
        assert args[args.index(flag)+1] == value
    assert '--memory=1g' in args and '--cpus=1' in args
    assert 'NAUTILUS_SMOKE_WHEEL=selected.whl' in args
    body = args[-1]
    assert '--no-index' in body and '--no-deps' in body
    assert 'from nautilus_trader.model import InstrumentId' in body
    assert 'native.replay_shared_inputs' in body
    assert 'model.identifiers' not in body
