from __future__ import annotations

import json
from pathlib import Path

import pytest
from types import SimpleNamespace

from server.manager.domain.navigation_registry import navigation_modules
from server.manager.services.agent_app_server_launch import AgentAppServerLaunch
from server.manager.services.mihomo_supervisor import MihomoError, MihomoSupervisor


def test_runtime_config_forces_loopback_and_disables_tun(tmp_path: Path) -> None:
    pytest.importorskip("yaml")
    source = tmp_path / "source.yaml"
    source.write_text(
        """
external-controller: 0.0.0.0:9999
secret: leaked
allow-lan: true
mixed-port: 1234
tun:
  enable: true
proxies: []
""",
        encoding="utf-8",
    )
    supervisor = MihomoSupervisor(
        tmp_path / "state",
        binary="/missing/mihomo",
        source_config=str(source),
    )

    supervisor._write_runtime_config(source)

    import yaml

    value = yaml.safe_load(
        (tmp_path / "state" / "mihomo" / "config.yaml").read_text(
            encoding="utf-8",
        ),
    )
    assert value["external-controller"] == "127.0.0.1:9090"
    assert value["secret"] == ""
    assert value["allow-lan"] is False
    assert value["bind-address"] == "127.0.0.1"
    assert value["mixed-port"] == 7890
    assert value["socks-port"] == 0
    assert value["tun"]["enable"] is False


def test_start_without_binary_fails_closed(tmp_path: Path) -> None:
    source = tmp_path / "source.yaml"
    source.write_text("proxies: []\n", encoding="utf-8")
    supervisor = MihomoSupervisor(
        tmp_path / "state",
        binary="/missing/mihomo",
        source_config=str(source),
    )

    value = supervisor.start()

    assert value["running"] is False
    assert value["last_error"] == "Mihomo binary is unavailable"
    assert json.loads(
        (tmp_path / "state" / "mihomo" / "state.json").read_text(
            encoding="utf-8",
        ),
    )["enabled"] is False


def test_api_endpoint_requires_running_process(tmp_path: Path) -> None:
    supervisor = MihomoSupervisor(tmp_path)

    with pytest.raises(MihomoError, match="not running"):
        supervisor.api_endpoint()


def test_start_waits_for_mixed_proxy_listener(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.yaml"
    source.write_text("proxies: []\n", encoding="utf-8")

    class FakeProcess:
        def __init__(self) -> None:
            self.returncode = None

        def poll(self) -> int | None:
            return self.returncode

        def terminate(self) -> None:
            self.returncode = 0

        def wait(self, timeout: float | None = None) -> int:
            return 0

    process = FakeProcess()
    monkeypatch.setattr(
        "server.manager.services.mihomo_supervisor.subprocess.Popen",
        lambda *args, **kwargs: process,
    )
    supervisor = MihomoSupervisor(
        tmp_path / "state",
        binary="/bin/sh",
        source_config=str(source),
    )
    monkeypatch.setattr(supervisor, "_version", lambda: "v1.19.30")
    readiness = iter((False, True))
    monkeypatch.setattr(supervisor, "_proxy_ready", lambda: next(readiness))

    value = supervisor.start()

    assert value["running"] is True
    assert value["version"] == "v1.19.30"
    supervisor.stop()


def test_mihomo_module_is_super_admin_only() -> None:
    assert not any(item["id"] == "mihomo" for item in navigation_modules(None))
    modules = navigation_modules({"role": "super_admin"})
    module = next(item for item in modules if item["id"] == "mihomo")
    assert module["homeVisible"] is True
    assert module["path"] == "/mihomo"


def test_agent_proxy_environment_is_child_scoped() -> None:
    runtime = SimpleNamespace(
        environment=lambda: {
            "PATH": "/usr/bin",
            "FACTORTESTER_MANAGER_PUBLIC_ENDPOINT": "https://manager.example:7998",
        },
    )
    launch = AgentAppServerLaunch(
        runtime=runtime,
        provider={"secret": "not-returned"},
        codex_binary="codex",
        factor_tester_cli="factortester",
        proxy_url="http://127.0.0.1:7890",
    )

    value = launch.environment()

    assert value["HTTPS_PROXY"] == "http://127.0.0.1:7890"
    assert value["ALL_PROXY"] == "http://127.0.0.1:7890"
    assert "manager.example" in value["NO_PROXY"]
    assert "127.0.0.1" in value["NO_PROXY"]
    assert value["FACTORTESTER_AGENT_TOKEN"] == "not-returned"
