"""Shared access lists retain pagination/filter and enforce action ownership."""
from pathlib import Path
import subprocess


def test_access_tables_js():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(['node', 'tests/js/test_access_tables.js'], cwd=root,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
