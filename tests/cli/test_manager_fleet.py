from __future__ import annotations

from pathlib import Path

from tools.cli.manager import fleet


class _Config:
    base_url = "http://127.0.0.1:7998"


class _Client:
    def __init__(self) -> None:
        self.config = _Config()
        self.services = {
            "worktree-141": {"port": 8141, "running": True},
            "worktree-176": {"port": 8176, "running": True},
            "worktree-178": {"port": 8178, "running": False},
        }
        self.actions: list[tuple[str, str]] = []

    def session(self) -> dict:
        return {"capabilities": {"manager": True}}

    def instances(self) -> dict:
        return {
            "worktrees": [
                {"instance_id": identity, **value}
                for identity, value in self.services.items()
            ]
        }

    def action(self, instance_id: str, action: str) -> dict:
        self.actions.append((instance_id, action))
        self.services[instance_id]["running"] = action == "start"
        return {"success": True}


def test_restart_fleet_restores_only_the_captured_running_set(monkeypatch) -> None:
    client = _Client()
    resolved: list[tuple[str, str]] = []
    monkeypatch.setattr(
        fleet,
        "resolve_manager_source",
        lambda root, **options: (
            resolved.append((options["source_mode"], options["source_revision"]))
            or root
        ),
    )
    manager_restarts: list[Path] = []

    receipt = fleet.restart_managed_fleet(
        client=client,
        source_root=Path("/tmp/worktree"),
        source_mode="git-commit",
        source_revision="a" * 40,
        port_stop_modes={8141: "force"},
        manager_restart=lambda *, source_root: manager_restarts.append(source_root),
    )

    assert resolved == [("git-commit", "a" * 40)]
    assert manager_restarts == [Path("/tmp/worktree")]
    assert client.actions == [
        ("worktree-141", "force-stop"),
        ("worktree-176", "stop"),
        ("worktree-141", "start"),
        ("worktree-176", "start"),
    ]
    assert receipt.restarted_ports == (8141, 8176)
    assert receipt.port_stop_modes == ("8141=force",)


def test_restart_fleet_rejects_special_instruction_for_stopped_port(monkeypatch) -> None:
    client = _Client()
    monkeypatch.setattr(fleet, "resolve_manager_source", lambda root, **_: root)

    try:
        fleet.restart_managed_fleet(
            client=client,
            source_root=Path("/tmp/worktree"),
            port_stop_modes={8178: "force"},
            manager_restart=lambda **_: {},
        )
    except RuntimeError as exc:
        assert "未运行" in str(exc)
    else:
        raise AssertionError("a stopped port must not receive a fleet stop override")
