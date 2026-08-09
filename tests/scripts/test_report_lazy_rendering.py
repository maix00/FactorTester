"""Behavior contract for report leaf lazy rendering."""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_report_leaf_rendering_waits_for_intersection() -> None:
    fixture = ROOT / "tests" / "scripts" / "fixtures" / "report_lazy_renderer.js"
    result = subprocess.run(
        ["node", str(fixture)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_large_report_tables_render_in_idle_chunks() -> None:
    fixture = ROOT / "tests" / "scripts" / "fixtures" / "report_table_rendering.js"
    result = subprocess.run(
        ["node", str(fixture)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"
