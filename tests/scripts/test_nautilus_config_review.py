"""Focused browser configuration review and fail-closed submission contract."""

from pathlib import Path
import subprocess


def test_nautilus_config_review() -> None:
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["node", "tests/scripts/fixtures/nautilus_config_review.js"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
