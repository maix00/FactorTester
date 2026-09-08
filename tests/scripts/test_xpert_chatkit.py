"""Local UI transport and application-owned drawer regression contracts."""
from pathlib import Path
import subprocess
import pytest
from server.manager.web.assets import static_file

ROOT = Path(__file__).resolve().parents[2]

@pytest.mark.parametrize('name', ['test_xpert_process_history.js', 'test_xpert_transport.js', 'test_xpert_steer.js', 'test_page_agent_drawer_lazy.js',
    'test_profile_agent_runtime_controls.js', 'test_profile_agent_view_switch.js', 'test_profile_agent_stream.js'])
def test_xpert_ui_contracts(name):
    result = subprocess.run(['node', str(ROOT / 'tests/js' / name)], cwd=ROOT,
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_local_ui_entry_and_vendor_allowlist():
    body, mime = static_file('vendor/xpert-chatkit/index.html')
    assert mime == 'text/html'
    assert b'frame-bootstrap' in body
    script, mime = static_file('vendor/xpert-chatkit/xpert-chatkit.js')
    assert b'xpertai-chatkit' in script
    with pytest.raises(ValueError):
        static_file('vendor/xpert-chatkit/../../profile/agent-chat.js')
