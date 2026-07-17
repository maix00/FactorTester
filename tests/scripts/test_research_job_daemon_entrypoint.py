from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import sysconfig


def test_daemon_entrypoint_bootstraps_repo_without_editable_install(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = sysconfig.get_paths()["purelib"]

    completed = subprocess.run(
        [
            sys.executable,
            "-S",
            str(repo_root / "scripts" / "research_job_daemon.py"),
            "--help",
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--deployment-id" in completed.stdout
