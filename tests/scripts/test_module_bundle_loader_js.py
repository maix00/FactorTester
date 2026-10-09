"""The lazy module loader prefers a group bundle and still falls back."""
from pathlib import Path
import subprocess


def test_module_bundle_loader_js():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["node", "tests/js/test_module_bundle_loader.js"],
        cwd=root, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_app_shell_startup_js():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["node", "tests/js/test_app_shell_startup.js"],
        cwd=root, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
