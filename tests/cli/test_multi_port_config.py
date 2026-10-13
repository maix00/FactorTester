from __future__ import annotations

from pathlib import Path

from tools.cli.http import ClientConfig, HttpSession, cookie_path_for


def test_cli_service_port_selection_does_not_rewrite_manager_origin(
    monkeypatch, tmp_path,
) -> None:
    from tools.cli.core import context
    from tools.cli.http import save_config

    monkeypatch.setenv("FACTORTESTER_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    save_config(ClientConfig("https://manager.example:9443"))
    monkeypatch.setattr(context, "requested_ports", lambda: (8142,))
    monkeypatch.setattr(context, "load_capability", lambda: None)

    client = context.client_from_config()

    assert client.session.base_url == "https://manager.example:9443"


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


def test_native_selection_is_a_fallback_and_explicit_config_remains_authoritative(tmp_path, monkeypatch):
    from click.testing import CliRunner
    from tools.cli.commands.auth import configure
    from tools.cli.http import load_config, native_selection_path, save_native_selection

    monkeypatch.setenv('FACTORTESTER_CONFIG', str(tmp_path / 'config.json'))
    save_native_selection(ClientConfig('https://native.example:7998'))
    assert load_config().base_url == 'https://native.example:7998'
    assert not (tmp_path / 'config.json').exists()

    configured = CliRunner().invoke(configure, ['--base-url', 'https://cli.example:7998'])
    assert configured.exit_code == 0, configured.output
    save_native_selection(ClientConfig('http://127.0.0.1:8141'))
    assert load_config().base_url == 'https://cli.example:7998'
    assert native_selection_path().read_text().count('127.0.0.1:8141') == 1


def test_server_discovery_uses_declared_port_and_checks_identity(monkeypatch):
    from tools.cli import server_connection as m
    seen = []
    class Session:
        def __init__(self, url, **kwargs):
            self.url = url
        def request(self, *args, **kwargs):
            assert "extra_headers" not in kwargs
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


def test_data_plane_trust_does_not_cross_unrelated_hosts(tmp_path, monkeypatch):
    from tools.cli import native_session
    import ssl
    monkeypatch.setenv('FACTORTESTER_HOME', str(tmp_path))
    native_session.save_session('https://manager.example:9443', 'alice', 'secret', 'trusted-pem')
    seen = []
    class Context:
        def load_verify_locations(self, **kwargs):
            seen.append(kwargs)
    monkeypatch.setattr(ssl, 'create_default_context', Context)
    assert native_session.transfer_tls_context('https://manager.example:9555/object', 'https://manager.example:9443') is not None
    assert seen == [{'cadata': 'trusted-pem'}]
    assert native_session.transfer_tls_context('https://other.example/object', 'https://manager.example:9443') is None
    assert native_session.transfer_tls_context('http://manager.example/object', 'https://manager.example:9443') is None


def test_session_rejects_cross_origin_urls_and_redirects(tmp_path, monkeypatch):
    import pytest
    from urllib.request import Request
    from urllib.error import HTTPError
    from tools.cli.http import _OriginBoundRedirect
    monkeypatch.setenv('FACTORTESTER_HOME', str(tmp_path))
    session = HttpSession('https://manager.example:9443', bearer_token='secret')
    with pytest.raises(ValueError, match='origin'):
        session.get('https://manager.example:9555/api/me')
    with pytest.raises(HTTPError, match='cross-origin'):
        _OriginBoundRedirect().redirect_request(Request('https://manager.example:9443/api/me'), None, 302,
            'found', {}, 'https://other.example/api/me')
