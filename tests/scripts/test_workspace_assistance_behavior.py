"""Run browser-state contracts in the standard regression suite."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("fixture", [
    "test_page_assistance_workspace.js",
    "test_report_live_updates.js",
])
def test_workspace_behavior(fixture: str) -> None:
    result = subprocess.run(
        ["node", str(ROOT / "tests" / "js" / fixture)],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr or result.stdout
