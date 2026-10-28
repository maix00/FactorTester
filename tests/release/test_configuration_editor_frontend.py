"""Focused frontend contract: real compiler and draft/i18n/component tests."""
from pathlib import Path
import subprocess


def test_configuration_editor_frontend_contract():
    folder = Path(__file__).resolve().parents[2] / "web" / "app"
    assert (folder / "node_modules" / "@rjsf" / "core").is_dir(), "Run npm ci in web/app before frontend checks"
    result = subprocess.run(["npm", "run", "check"], cwd=folder, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
