"""The business app's worker count is deployment-configurable.

The platform default collapses to two threads on a small Linux host, which
serialises concurrent Web/API requests on a public deployment; the deploy
environment must be able to raise it without editing code.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _threads(env_value: str | None = None) -> int:
    env = dict(os.environ)
    env.pop("FACTORTESTER_WAITRESS_THREADS", None)
    if env_value is not None:
        env["FACTORTESTER_WAITRESS_THREADS"] = env_value
    result = subprocess.run(
        [sys.executable, "-c", "import settings; print(settings.WAITRESS_THREADS)"],
        cwd=ROOT, capture_output=True, text=True, timeout=120, env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return int(result.stdout.strip().splitlines()[-1])


def test_worker_threads_follows_the_deployment_override():
    default = _threads()
    assert default >= 1
    assert _threads("8") == 8
    assert _threads("1") == 1
    # An unusable value keeps the platform default instead of breaking startup.
    assert _threads("abc") == default
    assert _threads("") == default
    # A typo cannot open an unbounded number of threads.
    assert _threads("999") == 64
