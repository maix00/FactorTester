"""Behavior contract for Swift-owned Web reference tabs."""

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_reference_page_maps_stable_object_endpoints() -> None:
    fixture = ROOT / "tests" / "scripts" / "fixtures" / "reference_page.js"
    result = subprocess.run(
        ["node", str(fixture)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"
