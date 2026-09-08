from pathlib import Path
import subprocess

def test_workspace_browser_interactions():
    subprocess.run(["node", "tests/js/test_profile_workspace_browser.js"],
                   cwd=Path(__file__).resolve().parents[2], check=True)
