"""A tab keeps its header actions across tab switches.

Switching tabs clears the live toolbar before the target view is restored, so
an empty capture must not erase the actions a tab parked earlier.
"""

from pathlib import Path
import subprocess


def test_tab_toolbar_parking_js():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["node", "tests/js/test_tab_toolbar_parking.js"],
        cwd=root, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
