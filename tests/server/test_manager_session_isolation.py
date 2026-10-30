from __future__ import annotations

import settings as Settings

from server.manager.runtime import ManagerState


def test_embedded_manager_defaults_sessions_to_its_state_root(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "shared.sqlite")

    state = ManagerState(
        tmp_path / "repo",
        "python",
        state_root=tmp_path / "manager-state",
    )

    assert state.sessions_db_path == (
        tmp_path / "manager-state" / "manager-sessions.sqlite"
    ).resolve()
    assert state.sessions_db_path != (tmp_path / "shared.sqlite").resolve()


def test_manager_reads_the_same_traderesearch_deployment_identity_as_flask(tmp_path, monkeypatch):
    for suffix in ("SERVER_ROLE", "SERVER_ID", "PUBLIC_SERVER", "REQUIRE_DEVICE_AUTH", "MANAGED_ORGANIZATIONS"):
        monkeypatch.delenv("FACTORTESTER_" + suffix, raising=False)
    monkeypatch.setenv("TRADERESEARCH_SERVER_ROLE", "main")
    monkeypatch.setenv("TRADERESEARCH_SERVER_ID", "public-a")
    monkeypatch.setenv("TRADERESEARCH_PUBLIC_SERVER", "1")
    monkeypatch.setenv("TRADERESEARCH_MANAGED_ORGANIZATIONS", "org-a")
    state = ManagerState(tmp_path / "repo", "python", state_root=tmp_path / "state")
    assert state.server_role == "main"
    assert state.server_id == "public-a"
    assert state.public_server is True
    assert state.managed_organizations == ("org-a",)
