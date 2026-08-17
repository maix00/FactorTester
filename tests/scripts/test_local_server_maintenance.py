from __future__ import annotations

from pathlib import Path

import pytest

from scripts.server import local_manager_service


ROOT = Path(__file__).resolve().parents[2]
LOCAL_SCRIPT = ROOT / "scripts" / "server" / "factortester_container.sh"
COMPOSE = ROOT / "deploy" / "docker" / "factortester-server" / "compose.yaml"


def _service(port: int = 8141, *, running: bool = True) -> dict:
    return {
        "instance_id": "worktree-test-service",
        "port": port,
        "running": running,
        "daemon_running": running,
        "port_in_use": running,
    }


def test_local_script_has_separate_manager_and_service_lifecycle_commands() -> None:
    source = LOCAL_SCRIPT.read_text(encoding="utf-8")

    for command in (
        "manager-reload",
        "manager-restart",
        "service-reload",
        "service-restart",
        "service-start",
        "service-stop",
        "stack-restart",
        "hot-reload-status",
    ):
        assert command in source
    assert "docker.sock" not in source


def test_local_compose_enables_hot_reload_by_default() -> None:
    source = COMPOSE.read_text(encoding="utf-8")
    assert "FACTORTESTER_HOT_RELOAD: ${FACTORTESTER_HOT_RELOAD:-1}" in source
    assert "restart: unless-stopped" in source


def test_service_helper_resolves_port_to_opaque_instance_and_waits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability = tmp_path / "manager-capability.key"
    capability.write_text("opaque-capability\n", encoding="ascii")
    calls: list[tuple[str, str, dict[str, str] | None]] = []
    snapshots = iter([
        {"worktrees": [_service()]},
        {"worktrees": [_service()]},
    ])

    def fake_request(
        base_url: str,
        token: str,
        path: str,
        *,
        form: dict[str, str] | None = None,
        timeout: float,
    ) -> dict:
        assert base_url == "http://127.0.0.1:7998"
        assert token == "opaque-capability"
        calls.append((base_url, path, form))
        if path == "/restart-api":
            return {"success": True, "message": "restarted"}
        if path == "/api/worktrees":
            return next(snapshots)
        raise AssertionError(path)

    monkeypatch.setattr(local_manager_service, "_request_json", fake_request)
    result = local_manager_service.perform(
        base_url="http://127.0.0.1:7998",
        capability_file=capability,
        port=8141,
        action="reload-api",
        timeout=1,
    )

    assert result == {
        "success": True,
        "action": "reload-api",
        "port": 8141,
        "instance_id": "worktree-test-service",
        "running": True,
        "message": "restarted",
    }
    assert calls == [
        ("http://127.0.0.1:7998", "/api/worktrees", None),
        (
            "http://127.0.0.1:7998",
            "/restart-api",
            {"instance_id": "worktree-test-service"},
        ),
        ("http://127.0.0.1:7998", "/api/worktrees", None),
    ]


def test_service_helper_rejects_ambiguous_port(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability = tmp_path / "manager-capability.key"
    capability.write_text("opaque-capability", encoding="ascii")
    monkeypatch.setattr(
        local_manager_service,
        "_request_json",
        lambda *args, **kwargs: {
            "worktrees": [_service(), {**_service(), "instance_id": "other"}],
        },
    )

    with pytest.raises(local_manager_service.ManagerServiceError, match="多个"):
        local_manager_service.perform(
            base_url="http://127.0.0.1:7998",
            capability_file=capability,
            port=8141,
            action="restart-bundle",
            timeout=1,
        )


def test_service_helper_never_serializes_capability_in_result() -> None:
    source = (ROOT / "scripts" / "server" / "local_manager_service.py").read_text(
        encoding="utf-8"
    )
    assert "print(token" not in source
    assert "docker.sock" not in source
