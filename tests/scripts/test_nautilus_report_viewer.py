"""Focused browser-module contract for isolated NautilusTrader HTML reports."""

from pathlib import Path
import subprocess


def test_nautilus_report_viewer() -> None:
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["node", "tests/scripts/fixtures/nautilus_report_viewer.js"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
