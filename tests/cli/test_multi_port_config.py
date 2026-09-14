from __future__ import annotations

from pathlib import Path

from tools.cli.http import ClientConfig, HttpSession, cookie_path_for


def test_client_config_replaces_only_listener_port() -> None:
    config = ClientConfig("http://127.0.0.1:8141/base")
    assert config.for_port(8142).base_url == "http://127.0.0.1:8142/base"


def test_http_sessions_use_distinct_cookie_files(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path))
    first = HttpSession("http://127.0.0.1:8141")
    second = HttpSession("http://127.0.0.1:8142")
    assert Path(first.cookie_jar.filename) == cookie_path_for("http://127.0.0.1:8141")
    assert Path(second.cookie_jar.filename) == cookie_path_for("http://127.0.0.1:8142")
    assert first.cookie_jar.filename != second.cookie_jar.filename


def test_configure_reuses_native_selected_server_without_guessing_port(tmp_path, monkeypatch):
    from click.testing import CliRunner
    from tools.cli.commands.auth import configure
    from tools.cli.http import save_config, load_config
    monkeypatch.setenv('FACTORTESTER_CONFIG', str(tmp_path / 'config.json'))
    save_config(ClientConfig('https://manager.example:9443'))
    result = CliRunner().invoke(configure, [])
    assert result.exit_code == 0
    assert load_config().base_url == 'https://manager.example:9443'
    assert CliRunner().invoke(configure, ['--host', 'manager.example']).exit_code == 0
    assert load_config().base_url == 'https://manager.example'


def test_server_discovery_uses_declared_port_and_checks_identity(monkeypatch):
    from tools.cli import server_connection as m
    seen = []
    class Session:
        def __init__(self, url, **kwargs):
            self.url = url
        def request(self, *args, **kwargs):
            seen.append(self.url)
            if len(seen) == 1:
                return {'server_id': 'seed', 'internal_server_targets': [
                    {'server_id': 'lan', 'online': True, 'addresses': ['192.168.1.5'], 'manager_port': 9333}]}
            return {'server_id': 'lan'}
    monkeypatch.setattr(m, 'HttpSession', Session)
    assert m.discover_server(ClientConfig('https://seed.example'), 'lan').base_url == 'http://192.168.1.5:9333'
    assert seen == ['https://seed.example', 'http://192.168.1.5:9333']


def test_login_reuses_native_session_without_prompting_for_password(monkeypatch):
    from click.testing import CliRunner
    from types import SimpleNamespace
    from tools.cli.commands import auth
    monkeypatch.setattr(auth, 'client_from_config', lambda **kw: SimpleNamespace(
        session=SimpleNamespace(bearer_token='opaque', agent_capability=None),
        current_principal=lambda: {'username': 'alice', 'alias': 'Alice'}))
    result = CliRunner().invoke(auth.login, [])
    assert result.exit_code == 0, result.output
    assert 'alice' in result.output and 'Password' not in result.output
    assert CliRunner().invoke(auth.login, ['--username', 'bob']).exit_code != 0


def test_cli_discovery_marker_does_not_disable_secure_transport():
    from types import SimpleNamespace
    from server.manager.http.request_security import RequestSecurityMixin
    for secure in (True, False):
        handler = SimpleNamespace(headers={'X-FactorTester-Client': 'cli'},
            _has_secure_ui_transport=lambda: secure)
        assert RequestSecurityMixin._is_swift_network_discovery_request(handler) is secure
