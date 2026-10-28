"""Read-only trading desk contract and stale-response protection."""

from pathlib import Path
import subprocess


def test_nautilus_trading_workbench() -> None:
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["node", "tests/scripts/fixtures/nautilus_trading_workbench.js"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
