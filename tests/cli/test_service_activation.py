from __future__ import annotations

from tools.cli.release import service_activation


def test_release_activation_restarts_the_unique_manager_port(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    class Config:
        base_url = "http://127.0.0.1:7998"

    class Credentials:
        def __init__(self, _config) -> None:
            pass

        def read(self) -> str:
            return "manager-session"

    class Client:
        def __init__(self, config, *, token: str, timeout: float) -> None:
            assert config.base_url == "http://127.0.0.1:7998"
            assert token == "manager-session"
            assert timeout == 180

        def instances(self) -> dict:
            return {"worktrees": [{
                "instance_id": "worktree-141",
                "port": 8141,
            }]}

        def action(self, instance_id: str, action: str) -> dict:
            calls.append((instance_id, action))
            return {"success": True, "message": "started api"}

    monkeypatch.setattr(service_activation, "load_manager_config", lambda: Config())
    monkeypatch.setattr(service_activation, "ManagerCredentialStore", Credentials)
    monkeypatch.setattr(service_activation, "ManagerClient", Client)

    receipt = service_activation.restart_release_service(port=8141)

    assert calls == [("worktree-141", "restart-all")]
    assert receipt.port == 8141
    assert receipt.action == "restart-bundle"


def test_release_activation_rejects_an_ambiguous_port(monkeypatch) -> None:
    class Config:
        base_url = "http://127.0.0.1:7998"

    class Credentials:
        def __init__(self, _config) -> None:
            pass

        def read(self) -> str:
            return "manager-session"

    class Client:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def instances(self) -> dict:
            return {"worktrees": [{"port": 8141}, {"port": 8141}]}

    monkeypatch.setattr(service_activation, "load_manager_config", lambda: Config())
    monkeypatch.setattr(service_activation, "ManagerCredentialStore", Credentials)
    monkeypatch.setattr(service_activation, "ManagerClient", Client)

    try:
        service_activation.restart_release_service(port=8141)
    except RuntimeError as exc:
        assert "唯一" in str(exc)
    else:
        raise AssertionError("ambiguous port must be rejected")
