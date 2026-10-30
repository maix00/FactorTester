from __future__ import annotations

import json

from click.testing import CliRunner

from tools.cli.manager_app import manager_cli
from tools.cli.manager.config import ManagerConfig


def test_manager_config_is_separate_from_server_config(tmp_path, monkeypatch) -> None:
    manager_config = tmp_path / "manager.json"
    server_config = tmp_path / "server.json"
    monkeypatch.setenv("FACTORTESTER_MANAGER_CONFIG", str(manager_config))
    monkeypatch.setenv("FACTORTESTER_CONFIG", str(server_config))

    result = CliRunner().invoke(manager_cli, [
        "configure",
        "--host", "127.0.0.1",
        "--port", "7998",
        "--json",
    ])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["manager_url"] == "http://127.0.0.1:7998"
    assert manager_config.is_file()
    assert not server_config.exists()


def test_remote_manager_configuration_requires_https() -> None:
    try:
        ManagerConfig.from_url("http://manager.example:7998")
    except ValueError as exc:
        assert "requires HTTPS" in str(exc)
    else:
        raise AssertionError("remote HTTP Manager URL was accepted")


def test_manager_login_reuses_keycloak_desktop_session(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "manager.json"
    monkeypatch.setenv("FACTORTESTER_MANAGER_CONFIG", str(config_path))
    CliRunner().invoke(manager_cli, [
        "configure", "--url", "http://127.0.0.1:7998",
    ])
    saved = []
    monkeypatch.setattr(
        "tools.cli.native_session.load_token",
        lambda endpoint: "session-token" if endpoint == "http://127.0.0.1:7998" else "",
    )
    monkeypatch.setattr(
        "tools.cli.manager.commands.ManagerClient.require_manager",
        lambda _self: {
            "success": True,
            "username": "root@1",
            "capabilities": {"manager": True},
        },
    )
    monkeypatch.setattr(
        "tools.cli.manager.commands.ManagerCredentialStore.write",
        lambda _self, token: saved.append(token),
    )

    result = CliRunner().invoke(manager_cli, [
        "login",
        "--json",
    ])

    assert result.exit_code == 0, result.output
    assert saved == ["session-token"]
    assert "session-token" not in result.output


def test_manager_login_does_not_offer_password_authentication(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(
        "FACTORTESTER_MANAGER_CONFIG",
        str(tmp_path / "manager.json"),
    )
    CliRunner().invoke(manager_cli, ["configure"])
    monkeypatch.setattr("tools.cli.native_session.load_token", lambda _endpoint: "")
    result = CliRunner().invoke(manager_cli, ["login", "--username", "root"])
    assert result.exit_code != 0
    assert "no such option" in result.output.lower()


def test_manager_login_does_not_persist_non_manager_session(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(
        "FACTORTESTER_MANAGER_CONFIG",
        str(tmp_path / "manager.json"),
    )
    CliRunner().invoke(manager_cli, ["configure"])
    saved = []
    monkeypatch.setattr("tools.cli.native_session.load_token", lambda _endpoint: "bad-token")
    def reject_non_manager(_self):
        raise PermissionError("当前账号没有 Manager 管理权限（需要 super_admin）")
    monkeypatch.setattr(
        "tools.cli.manager.commands.ManagerClient.require_manager",
        reject_non_manager,
    )
    monkeypatch.setattr(
        "tools.cli.manager.commands.ManagerCredentialStore.write",
        lambda _self, token: saved.append(token),
    )

    result = CliRunner().invoke(manager_cli, [
        "login",
    ])

    assert result.exit_code != 0
    assert "没有 Manager 管理权限" in result.output
    assert saved == []


def test_manager_service_restart_commands_map_to_distinct_backend_actions(
    monkeypatch,
) -> None:
    actions = []
    client = type("Client", (), {
        "instances": lambda _self: {"worktrees": [{
            "instance_id": "worktree-opaque",
            "port": 8141,
        }]},
        "action": lambda _self, instance, action: (
            actions.append((instance, action))
            or {
                "success": True,
                "instance_id": instance,
                "message": "submitted",
            }
        ),
    })()
    monkeypatch.setattr(
        "tools.cli.manager.commands._authenticated_client",
        lambda: (client, object()),
    )

    runner = CliRunner()
    web = runner.invoke(manager_cli, [
        "services", "restart-api", "8141", "--json",
    ])
    complete = runner.invoke(manager_cli, [
        "services", "restart-bundle", "8141", "--json",
    ])

    assert web.exit_code == 0, web.output
    assert complete.exit_code == 0, complete.output
    assert actions == [
        ("worktree-opaque", "restart-api"),
        ("worktree-opaque", "restart-bundle"),
    ]
    assert json.loads(web.output)["port"] == 8141
    assert "instance_id" not in web.output


def test_manager_action_rejects_unknown_or_ambiguous_port(monkeypatch) -> None:
    client = type("Client", (), {
        "instances": lambda _self: {"worktrees": [
            {"instance_id": "first", "port": 8141},
            {"instance_id": "second", "port": 8141},
        ]},
        "action": lambda _self, _instance, _action: {},
    })()
    monkeypatch.setattr(
        "tools.cli.manager.commands._authenticated_client",
        lambda: (client, object()),
    )

    duplicate = CliRunner().invoke(manager_cli, [
        "services", "restart-api", "8141", "--json",
    ])
    missing = CliRunner().invoke(manager_cli, [
        "services", "restart-api", "8999", "--json",
    ])

    assert duplicate.exit_code != 0
    assert "多个 TradeResearch 服务" in duplicate.output
    assert missing.exit_code != 0
    assert "没有找到" in missing.output


def test_manager_help_exposes_application_boundaries_only() -> None:
    manager_help = CliRunner().invoke(manager_cli, ["--help"])

    assert manager_help.exit_code == 0, manager_help.output
    assert "server" in manager_help.output
    assert "jobs" in manager_help.output
    assert "artifacts" in manager_help.output
    assert "research-graph" not in manager_help.output
    assert "restart-fleet" not in manager_help.output
    assert "\n  admin " not in manager_help.output


def test_server_access_is_read_only_server_owned_metadata(monkeypatch) -> None:
    client = type("Client", (), {
        "identity": lambda _self: {
            "success": True,
            "server": {"server_id": "public-1", "role": "main"},
            "management_access": [{
                "id": "operator-route",
                "kind": "server-declared",
                "endpoint": "opaque://server-provided",
            }],
        },
    })()
    monkeypatch.setattr(
        "tools.cli.manager.commands._authenticated_client",
        lambda: (client, object()),
    )

    result = CliRunner().invoke(manager_cli, ["server", "access", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["server"]["server_id"] == "public-1"
    assert payload["management_access"][0]["id"] == "operator-route"
