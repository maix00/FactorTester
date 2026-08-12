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
