from __future__ import annotations

import json
import threading
from pathlib import Path

from server.manager.services.agent_app_server_launch import AgentAppServerLaunch
from server.manager.services.agent_skill_runtime import AgentSkillRuntime
from server.manager.state.sessions import SessionStateMixin
from server.manager.storage.session_store import ManagerSessionStore
from tools.cli.catalog.store import LocalCatalogStore


class _SessionState(SessionStateMixin):
    def __init__(self, path: Path) -> None:
        self.session_store = ManagerSessionStore(path)
        self._session_lock = threading.RLock()
        self._session_cleanup_at = 0.0
        self._sessions = self._load_sessions()
        self._agent_sessions: dict[str, dict[str, str]] = {}

    @staticmethod
    def _alias_for_principal(principal: str) -> str:
        return principal.rsplit("@", 1)[0]


def test_agent_session_is_bound_to_profile_and_revoked(tmp_path: Path) -> None:
    state = _SessionState(tmp_path / "sessions.sqlite")

    issued = state.issue_agent_session(
        "GTHT@MaxJJW@1",
        "profile-main",
        "claim-1",
    )

    assert state.agent_session_matches(
        issued["token"],
        "profile-main",
        "claim-1",
    )
    assert not state.agent_session_matches(
        issued["token"],
        "profile-other",
        "claim-1",
    )
    state.revoke_agent_session(issued["token"])
    assert not state.agent_session_matches(
        issued["token"],
        "profile-main",
        "claim-1",
    )


def test_agent_cli_files_are_private_and_cleaned(tmp_path: Path) -> None:
    runtime = AgentSkillRuntime(tmp_path / "workspace")
    launch = AgentAppServerLaunch(
        runtime=runtime,
        provider={"secret": "provider-secret"},
        codex_binary="codex",
        factor_tester_cli="factortester",
        factor_tester_auth={
            "base_url": "http://manager:7998",
            "token": "agent-session-token",
            "profile_id": "profile-main",
            "claim_id": "claim-1",
            "principal": "GTHT@MaxJJW@1",
        },
        proxy_url="http://127.0.0.1:7890",
    )

    launch.write_factor_tester_config()
    capability = json.loads(
        launch.factor_tester_capability_path.read_text(encoding="utf-8"),
    )
    config = json.loads(
        launch.factor_tester_config_path.read_text(encoding="utf-8"),
    )
    environment = launch.environment()

    assert config == {"base_url": "http://manager:7998"}
    assert capability["token"] == "agent-session-token"
    assert capability["profile_id"] == "profile-main"
    assert launch.factor_tester_capability_path.stat().st_mode & 0o077 == 0
    assert "manager" in environment["NO_PROXY"]
    assert (
        environment["FACTORTESTER_CONFIG"] == "/workspace/.codex/factor-tester-cli.json"
    )
    assert environment["FACTORTESTER_AGENT_CAPABILITY_FILE"] == (
        "/workspace/.codex/factor-tester-agent.json"
    )
    assert environment["FACTORTESTER_CLIENT_ROOT"] == "/workspace/.factortester-client"
    assert environment["FACTORTESTER_PROFILE"] == "profile-main"
    assert environment["FACTORTESTER_AGENT_TOKEN"] == "provider-secret"
    profile = json.loads(
        (
            runtime.factor_tester_client_root / "profiles" / "profile-main.json"
        ).read_text(encoding="utf-8")
    )
    assert profile["profile_id"] == "profile-main"
    assert profile["session_binding"]["principal_ref"] == "GTHT@MaxJJW@1"
    assert profile["workspace_root"] == "/workspace"
    catalog = LocalCatalogStore(runtime.factor_tester_client_root).initialize()
    assert catalog["schema_version"] > 0

    launch.cleanup_factor_tester_config()

    assert not launch.factor_tester_config_path.exists()
    assert not launch.factor_tester_capability_path.exists()


def test_agent_profiles_have_distinct_writable_client_roots(tmp_path: Path) -> None:
    first = AgentSkillRuntime(tmp_path / "first")
    second = AgentSkillRuntime(tmp_path / "second")

    first.environment()
    second.environment()

    assert first.factor_tester_client_root != second.factor_tester_client_root
    assert first.factor_tester_client_root.is_dir()
    assert second.factor_tester_client_root.is_dir()


def test_agent_ca_bundle_verifies_local_tls_without_disabling_system_trust(tmp_path, monkeypatch):
    import ssl
    import subprocess
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.request import urlopen

    certificate, key = tmp_path / 'server.pem', tmp_path / 'server.key'
    subprocess.run([
        'openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
        '-keyout', str(key), '-out', str(certificate), '-days', '1',
        '-subj', '/CN=localhost', '-addext', 'subjectAltName=IP:127.0.0.1,DNS:localhost',
    ], check=True, capture_output=True)
    monkeypatch.setenv('FACTORTESTER_ARTIFACT_TLS_CERT', str(certificate))
    runtime = AgentSkillRuntime(tmp_path / 'workspace')
    launch = AgentAppServerLaunch(
        runtime=runtime, provider={'secret': 'test-provider'}, codex_binary='codex',
        factor_tester_auth={'base_url': 'http://127.0.0.1:17998', 'token': 'test-token',
                            'profile_id': 'self', 'claim_id': 'test-claim', 'principal': 'test-owner'},
    )
    launch.write_factor_tester_config()
    bundle = launch.factor_tester_ca_path.read_text()
    assert certificate.read_text().strip() in bundle
    assert 'PRIVATE KEY' not in bundle
    assert launch.factor_tester_ca_path.stat().st_mode & 0o077 == 0
    assert launch.environment()['SSL_CERT_FILE'] == '/workspace/.codex/factor-tester-ca.pem'
    trust = ssl.create_default_context(cafile=str(launch.factor_tester_ca_path))
    assert trust.check_hostname and trust.verify_mode == ssl.CERT_REQUIRED
    assert set(ssl.create_default_context().get_ca_certs(binary_form=True)) <= set(trust.get_ca_certs(binary_form=True))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Length', '2')
            self.end_headers()
            self.wfile.write(b'ok')

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server_trust = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_trust.load_cert_chain(certificate, key)
    server.socket = server_trust.wrap_socket(server.socket, server_side=True)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with urlopen(f'https://127.0.0.1:{server.server_port}/', context=trust, timeout=5) as response:
            assert response.read() == b'ok'
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
    launch.cleanup_factor_tester_config()
    assert not launch.factor_tester_ca_path.exists()
