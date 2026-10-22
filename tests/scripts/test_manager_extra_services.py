from pathlib import Path

from server.manager import runtime as manager


def test_manager_exposes_extra_service_ports(tmp_path, monkeypatch) -> None:
    source = tmp_path / "app-8001"
    source.mkdir()
    (source / "server").mkdir()
    state = manager.ManagerState(
        tmp_path, "python", fixed_port=8000, fixed_branch="main",
        extra_services=((8001, source),),
    )
    monkeypatch.setattr(state, "_worktree_entries", lambda: [])
    monkeypatch.setattr(state, "_port_is_in_use", lambda port: port in {8000, 8001})

    worktrees = {item.port: item for item in state.worktrees()}

    assert worktrees[8000].branch == "main"
    assert worktrees[8001].path == source
    assert worktrees[8001].branch == "service-8001"
    assert state.service_ports() == [8000, 8001]


def test_manager_rejects_extra_service_without_source(tmp_path) -> None:
    try:
        manager.ManagerState(
            tmp_path, "python", fixed_port=8000,
            extra_services=((8001, tmp_path / "missing"),),
        )
    except ValueError as error:
        assert "service source does not exist" in str(error)
    else:
        raise AssertionError("missing extra service source must be rejected")


def test_manager_can_run_fixed_port_from_separate_source(tmp_path, monkeypatch) -> None:
    manager_source = tmp_path / "manager"
    old_source = tmp_path / "old-app"
    manager_source.mkdir()
    old_source.mkdir()
    state = manager.ManagerState(
        manager_source, "python", fixed_port=8000, fixed_branch="main",
        fixed_source=old_source,
    )
    monkeypatch.setattr(state, "_worktree_entries", lambda: [])
    monkeypatch.setattr(state, "_port_is_in_use", lambda port: port == 8000)
    fixed = {item.port: item for item in state.worktrees()}[8000]
    assert fixed.path == old_source
