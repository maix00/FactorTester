from __future__ import annotations

import json
from types import SimpleNamespace

from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.commands import margin_budget as commands


def _configuration():
    return {
        "revision": 4,
        "payload": {"analyses": {"backtest": {
            "execution": {"settings": {"margin_mode": "auto", "allocation_policy": "equal_notional"}},
            "groups": [{"id": "A1", "name": "A1", "custom": {"preserved": True}}],
        }}},
    }


class _FakeClient:
    def __init__(self):
        self.configuration = _configuration()
        self.updated = None

    def get_workspace_configuration(self, workspace_id):
        assert workspace_id == "workspace-1"
        return self.configuration

    def update_workspace_configuration(self, workspace_id, *, expected_revision, payload):
        assert (workspace_id, expected_revision) == ("workspace-1", 4)
        self.updated = payload
        return {"revision": 5, "payload": payload}


def _install(monkeypatch):
    fake = _FakeClient()
    state = SimpleNamespace(workspace_id="workspace-1", configuration_revision=4)
    monkeypatch.setattr(commands, "client_from_config", lambda: fake)
    monkeypatch.setattr(commands, "load_state", lambda: state)
    monkeypatch.setattr(commands, "save_state", lambda value: None)
    return fake


def test_show_reports_enabled_margin_defaults_and_equal_notional(monkeypatch) -> None:
    _install(monkeypatch)

    result = CliRunner().invoke(cli, ["margin-budget", "show", "--json"])

    assert result.exit_code == 0, result.output
    row = json.loads(result.output)["strategies"][0]
    assert row["enabled"] is True
    assert row["allocation_policy"] == "equal_notional"
    assert row["target_margin_utilization"] == 0.30
    assert row["max_margin_utilization"] == 0.40


def test_configure_updates_workspace_and_validates_target_max_order(monkeypatch) -> None:
    fake = _install(monkeypatch)
    runner = CliRunner()

    updated = runner.invoke(cli, [
        "margin-budget", "configure", "A1",
        "--target", "0.75", "--max", "0.82", "--tolerance", "0.005", "--json",
    ])

    assert updated.exit_code == 0, updated.output
    group = fake.updated["analyses"]["backtest"]["groups"][0]
    assert group["target_margin_utilization"] == 0.75
    assert group["max_margin_utilization"] == 0.82
    assert group["custom"] == {"preserved": True}

    fake.updated = None
    rejected = runner.invoke(cli, [
        "margin-budget", "configure", "A1", "--target", "0.90", "--max", "0.85",
    ])
    assert rejected.exit_code != 0 and "target <= max" in rejected.output
    assert fake.updated is None
