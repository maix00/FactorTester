from __future__ import annotations

import pytest

from tools.cli.release import service_activation


class Config:
    base_url = "http://127.0.0.1:7998"


class Credentials:
    def __init__(self, _config) -> None:
        pass

    def read(self) -> str:
        return "manager-session"


def _install(monkeypatch, client_type) -> None:
    monkeypatch.setattr(service_activation, "load_manager_config", lambda: Config())
    monkeypatch.setattr(service_activation, "ManagerCredentialStore", Credentials)
    monkeypatch.setattr(service_activation, "ManagerClient", client_type)


def test_release_activation_restarts_manager_and_all_running_ports(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    class Client:
        services = {
            "worktree-141": {"port": 8141, "running": True},
            "worktree-176": {"port": 8176, "running": True},
            "worktree-178": {"port": 8178, "running": False},
        }

        def __init__(self, config, *, token: str, timeout: float) -> None:
            assert config.base_url == Config.base_url
            assert token == "manager-session"
            assert timeout == 180

        def session(self) -> dict:
            return {"capabilities": {"manager": True}}

        def instances(self) -> dict:
            return {"manager": {"release_root": "/tmp/client-releases"}, "worktrees": [
                {"instance_id": identity, **value}
                for identity, value in self.services.items()
            ]}

        def action(self, instance_id: str, action: str) -> dict:
            calls.append((instance_id, action))
            self.services[instance_id]["running"] = action == "start"
            return {"success": True}

    _install(monkeypatch, Client)
    monkeypatch.setattr(
        service_activation,
        "restart_manager_process",
        lambda *, source_root: calls.append(("manager", str(source_root))),
    )
    receipt = service_activation.restart_release_service(
        port=8141,
        source_root=service_activation.Path("/tmp/release-source"),
        source_revision="a" * 40,
    )

    assert calls == [
        ("worktree-141", "stop"),
        ("worktree-176", "stop"),
        ("manager", "/tmp/release-source"),
        ("worktree-141", "start"),
        ("worktree-176", "start"),
    ]
    assert receipt.restarted_ports == (8141, 8176)
    assert receipt.action == "restart-manager-and-services"
    assert receipt.release_root == "/tmp/client-releases"
    assert receipt.source_root == str(
        service_activation.Path("/tmp/release-source").resolve()
    )
    assert receipt.source_revision == "a" * 40


def test_release_activation_rejects_invalid_keychain_session(monkeypatch) -> None:
    class Client:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def session(self) -> dict:
            return {"capabilities": {"manager": False}}

    _install(monkeypatch, Client)
    with pytest.raises(RuntimeError, match="Keychain"):
        service_activation.restart_release_service(
            port=8141, source_root=service_activation.Path("/tmp/source"),
            source_revision="a" * 40,
        )


def test_release_activation_rejects_an_ambiguous_port(monkeypatch) -> None:
    class Client:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def session(self) -> dict:
            return {"capabilities": {"manager": True}}

        def instances(self) -> dict:
            return {
                "manager": {"release_root": "/tmp/releases"},
                "worktrees": [{"port": 8141}, {"port": 8141}],
            }

    _install(monkeypatch, Client)
    with pytest.raises(RuntimeError, match="唯一"):
        service_activation.restart_release_service(
            port=8141, source_root=service_activation.Path("/tmp/source"),
            source_revision="a" * 40,
        )


def test_release_activation_does_not_start_a_stopped_release_port(monkeypatch) -> None:
    class Client:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def session(self) -> dict:
            return {"capabilities": {"manager": True}}

        def instances(self) -> dict:
            return {"manager": {"release_root": "/tmp/releases"}, "worktrees": [{
                "instance_id": "worktree-141", "port": 8141, "running": False,
            }]}

    _install(monkeypatch, Client)
    with pytest.raises(RuntimeError, match="当前未开启"):
        service_activation.restart_release_service(
            port=8141, source_root=service_activation.Path("/tmp/source"),
            source_revision="a" * 40,
        )
