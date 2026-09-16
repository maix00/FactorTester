"""The factor-series viewer keeps one selectable entry per nested layer."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_factor_series_viewer_is_layer_aware():
    result = subprocess.run(
        ["node", "tests/js/test_factor_series_nested_layers.js"],
        cwd=REPO, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
