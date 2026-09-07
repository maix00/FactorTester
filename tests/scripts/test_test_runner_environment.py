"""The commit hook must not redirect test Git operations into the source repo."""

import os
from pathlib import Path
import subprocess


def test_runner_clears_hook_git_environment(tmp_path):
    root = Path(__file__).resolve().parents[2]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in {
        "python3": "exit 0\n",
        "conda": 'test -z "${GIT_DIR+x}" && test -z "${GIT_WORK_TREE+x}" && test -z "${GIT_INDEX_FILE+x}"\n',
    }.items():
        path = bin_dir / name
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)
    env = {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
           "GIT_DIR": str(root / ".git"), "GIT_WORK_TREE": str(root),
           "GIT_INDEX_FILE": str(tmp_path / "index")}
    result = subprocess.run(["bash", str(root / "scripts/test.sh")],
                            env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
