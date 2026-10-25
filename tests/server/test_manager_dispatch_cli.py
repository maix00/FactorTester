from __future__ import annotations

from click.testing import CliRunner

from tools.cli.manager.commands import manager


class _Client:
    def dispatch_overview(self):
        return {
            "outbox": {"pending": 1},
            "servers": [
                {"server_id": "local", "online": True,
                 "ports": [{"port": 8001, "queue": "factortester.jobs.local.8001",
                            "worker_online": True}]},
            ],
        }


def test_dispatch_status_json(monkeypatch):
    import tools.cli.manager.commands as commands

    monkeypatch.setattr(commands, "_authenticated_client", lambda: (_Client(), None))
    result = CliRunner().invoke(manager, ["dispatch", "status", "--json"])
    assert result.exit_code == 0, result.output
    assert '"queue": "factortester.jobs.local.8001"' in result.output


def test_dispatch_targets_table(monkeypatch):
    import tools.cli.manager.commands as commands

    monkeypatch.setattr(commands, "_authenticated_client", lambda: (_Client(), None))
    result = CliRunner().invoke(manager, ["dispatch", "targets"])
    assert result.exit_code == 0, result.output
    assert "8001" in result.output
    assert "worker=True" in result.output
