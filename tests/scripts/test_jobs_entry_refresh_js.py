"""Entering the task list must revalidate, not replay a cached page."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_task_list_revalidates_on_entry():
    result = subprocess.run(
        ["node", "tests/js/test_jobs_entry_refresh.js"],
        cwd=REPO, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
