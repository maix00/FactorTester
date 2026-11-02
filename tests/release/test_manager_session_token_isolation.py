"""Exercise the real Swift token store against an in-memory Security adapter."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.skipif(sys.platform != 'darwin', reason='requires macOS Security and Swift')
def test_session_token_migration_without_accessing_user_keychain(tmp_path):
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    xcode = Path('/Applications/Xcode.app/Contents/Developer')
    if xcode.is_dir():
        environment['DEVELOPER_DIR'] = str(xcode)
    binary = tmp_path / 'token-store-check'
    subprocess.run(['xcrun', 'swiftc', '-parse-as-library',
        str(root / 'tests/fixtures/manager_session_token_isolation.swift'),
        str(root / 'apple/Sources/Networking/ManagerSessionTokenStore.swift'),
        '-o', str(binary)], check=True, env=environment, capture_output=True, text=True)
    result = subprocess.run([str(binary)], check=True, capture_output=True, text=True)
    assert 'PASS: endpoint isolation and read-only, failure-safe Keychain migration' in result.stdout
