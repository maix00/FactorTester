import subprocess
from pathlib import Path


def test_user_display_keeps_identity_and_safe_text():
    root = Path(__file__).resolve().parents[2]
    subprocess.run(['node', str(root / 'tests/scripts/fixtures/user_display.js')], cwd=root, check=True)
