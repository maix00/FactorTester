from __future__ import annotations

import json

from click.testing import CliRunner

from tools.cli.manager_app import manager_cli


class _Client:
    actions = []

    def list_server_instances(self):
        return {
            "success": True,
            "instances": [{
                "instance_id": "worktree-opaque",
                "label": "issue-141",
                "branch": "fix/issue-141",
                "port": 8141,
                "running": True,
                "daemon_running": True,
                "port_in_use": True,
                "kind": "factortester",
                "status": "degraded",
            }],
        }

    def run_server_instance_action(self, instance_id, action):
        self.actions.append((instance_id, action))
        return {
            "success": True,
            "instance_id": instance_id,
            "action": action,
        }

    def list_global_jobs(self, *, limit, cursor):
        return {
            "success": True,
            "jobs": [{
                "job_id": "job-1",
                "owner": "MaxA",
                "status": "running",
            }],
            "page_size": 1,
            "has_more": False,
            "next_cursor": None,
            "request": {"limit": limit, "cursor": cursor},
        }


def test_admin_server_list_exposes_the_same_bounded_server_projection(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "tools.cli.commands.admin.client_from_config",
        lambda: _Client(),
    )

    result = CliRunner().invoke(manager_cli, ["admin", "server", "list", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["instances"][0]["instance_id"] == "worktree-opaque"
    assert "/Users/" not in result.output


def test_admin_server_list_text_uses_the_authoritative_status(monkeypatch) -> None:
    monkeypatch.setattr(
        "tools.cli.commands.admin.client_from_config",
        lambda: _Client(),
    )

    result = CliRunner().invoke(manager_cli, ["admin", "server", "list"])

    assert result.exit_code == 0, result.output
    assert "status=degraded" in result.output
    assert "running=" not in result.output


def test_admin_server_action_uses_opaque_instance_identity(monkeypatch) -> None:
    client = _Client()
    client.actions = []
    monkeypatch.setattr(
        "tools.cli.commands.admin.client_from_config",
        lambda: client,
    )

    result = CliRunner().invoke(
        manager_cli,
        ["admin", "server", "restart", "worktree-opaque", "--json"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["action"] == "restart"
    assert client.actions == [("worktree-opaque", "restart")]


def test_admin_server_supports_bounded_start_and_stop_actions(
    monkeypatch,
) -> None:
    client = _Client()
    client.actions = []
    monkeypatch.setattr(
        "tools.cli.commands.admin.client_from_config",
        lambda: client,
    )
    runner = CliRunner()

    for action in ("start", "stop"):
        result = runner.invoke(
            manager_cli,
            ["admin", "server", action, "worktree-opaque", "--json"],
        )
        assert result.exit_code == 0, result.output

    assert client.actions == [
        ("worktree-opaque", "start"),
        ("worktree-opaque", "stop"),
    ]


def test_admin_jobs_lists_the_bounded_global_projection(monkeypatch) -> None:
    monkeypatch.setattr(
        "tools.cli.commands.admin.client_from_config",
        lambda: _Client(),
    )

    result = CliRunner().invoke(
        manager_cli,
        ["admin", "jobs", "--limit", "25", "--cursor", "next", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["jobs"][0]["job_id"] == "job-1"
    assert payload["request"] == {"limit": 25, "cursor": "next"}
