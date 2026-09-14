from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.http import ClientConfig, HttpClientError, save_config
from tools.cli.release import profile_sync
from tools.cli.release.local_profile import new_local_profile


def _profile(tmp_path: Path, *, server_url: str = "http://127.0.0.1:8141"):
    return new_local_profile(
        profile_id="maxa",
        display_name="MaxA",
        server_url=server_url,
        workspace_root=tmp_path / "workspace",
        principal_ref="GTHT@MaxJJW@392452984564",
    )


def _configure_client(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "config.json"
    monkeypatch.setenv("FACTORTESTER_CONFIG", str(path))
    save_config(ClientConfig("http://127.0.0.1:8141"), path=path)


def test_manager_url_is_separate_from_profile_execution_url(
    tmp_path: Path, monkeypatch,
) -> None:
    _configure_client(tmp_path, monkeypatch)
    profile = _profile(tmp_path)

    assert profile_sync.manager_url_for_profile(profile) == (
        "http://127.0.0.1:8141"
    )
    assert profile_sync.manager_url_for_profile(
        profile, manager_url="http://127.0.0.1:7998/"
    ) == "http://127.0.0.1:7998"
    assert "server" not in profile


def test_sync_uses_native_session_without_operator_credentials(tmp_path: Path, monkeypatch) -> None:
    from tools.cli.native_session import save_session
    _configure_client(tmp_path, monkeypatch)
    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    profile = _profile(tmp_path)
    save_session("http://127.0.0.1:8141", "GTHT@MaxJJW@392452984564", "native-token")
    captured = {}
    class NativeClient:
        def __init__(self, session):
            captured["token"] = session.bearer_token
            captured["url"] = session.base_url
        def current_principal(self):
            return {"username": "GTHT@MaxJJW@392452984564"}
        def sync_profile(self, value):
            return {"synced": True}
    monkeypatch.setattr(profile_sync, "FactorTesterClient", NativeClient)
    assert profile_sync.sync_profile(profile)["synced"]
    assert captured == {"token": "native-token", "url": "http://127.0.0.1:8141"}


def test_sync_uses_selected_endpoint_with_legacy_cookie(
    tmp_path: Path, monkeypatch
) -> None:
    _configure_client(tmp_path, monkeypatch)
    profile = _profile(tmp_path)
    captured: dict[str, object] = {}


    class FakeLegacyClient:
        def __init__(self, session):
            captured["url"] = session.base_url

        def current_principal(self):
            return {"username": "GTHT@MaxJJW@392452984564"}

        def sync_profile(self, value):
            captured["profile"] = value
            return {"status": "synced", "synced": True}

    monkeypatch.setattr(profile_sync, "FactorTesterClient", FakeLegacyClient)

    receipt = profile_sync.sync_profile(profile)

    assert receipt["synced"] is True
    assert captured["url"] == "http://127.0.0.1:8141"


def test_sync_reports_pending_when_manager_session_is_unavailable(
    tmp_path: Path, monkeypatch
) -> None:
    _configure_client(tmp_path, monkeypatch)
    profile = _profile(tmp_path)

    class OfflineLegacyClient:
        def __init__(self, _session):
            pass

        def current_principal(self):
            raise HttpClientError(401, "http://127.0.0.1:7998/api/me", "login required")

    monkeypatch.setattr(profile_sync, "FactorTesterClient", OfflineLegacyClient)

    receipt = profile_sync.sync_profile(profile)

    assert receipt["status"] == "pending"
    assert receipt["pending"] is True
    assert receipt["synced"] is False
    assert receipt["manager_url"] == "http://127.0.0.1:8141"


def test_create_profile_auto_syncs_after_local_write(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "client-support"
    monkeypatch.setenv("FACTORTESTER_CLIENT_ROOT", str(root))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    captured: dict[str, object] = {}

    def fake_sync(profile, *, manager_url=""):
        captured["profile"] = profile
        captured["manager_url"] = manager_url
        return {"status": "synced", "synced": True, "pending": False}

    import tools.cli.commands.client_profile as command_module

    monkeypatch.setattr(command_module, "_sync_profile", fake_sync)
    result = CliRunner().invoke(cli, [
        "client", "profile", "create",
        "--profile-id", "maxa",
        "--display-name", "MaxA",
        "--server-url", "http://127.0.0.1:8141",
        "--manager-url", "http://127.0.0.1:7998",
        "--principal-ref", "GTHT@MaxJJW@392452984564",
    ])

    assert result.exit_code == 0, result.output
    receipt = json.loads(result.output)
    assert receipt["server_visibility_verified"] is True
    assert receipt["server_visibility_pending"] is False
    assert receipt["control_profile_sync"]["status"] == "synced"
    assert captured["manager_url"] == "http://127.0.0.1:7998"
    assert "server" not in captured["profile"]
