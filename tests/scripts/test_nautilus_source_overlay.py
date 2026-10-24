"""The source detail overlay uses the shared overlay and source-owned NT snapshot."""

from pathlib import Path
import subprocess


def test_nautilus_source_overlay() -> None:
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["node", "tests/scripts/fixtures/nautilus_source_overlay.js"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
