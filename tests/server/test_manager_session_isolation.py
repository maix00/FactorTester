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
