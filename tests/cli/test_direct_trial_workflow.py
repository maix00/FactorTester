from __future__ import annotations

import json

from click.testing import CliRunner

from tools.cli.app import cli


class _Client:
    def get_direct_trial_plan(self, trial_plan_ref):
        return {
            "trial_plan_ref": trial_plan_ref,
            "trial_plan_hash": "b" * 64,
            "trial_plan": {"trial_plan_id": "direct-plan-1"},
        }


def test_agent_can_read_a_direct_trial_plan(monkeypatch) -> None:
    monkeypatch.setattr(
        "tools.cli.commands.direct_trial.client_from_config",
        lambda: _Client(),
    )
    reference = "trial-plan:sha256:" + "b" * 64

    result = CliRunner().invoke(cli, [
        "trial-plan", "show", reference, "--json",
    ])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["trial_plan_ref"] == reference


def test_trial_plan_cli_exposes_only_historical_read(monkeypatch) -> None:
    result = CliRunner().invoke(cli, ["trial-plan", "--help"])
    assert result.exit_code == 0, result.output
    assert "show" in result.output
    assert "create" not in result.output
