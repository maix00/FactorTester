from __future__ import annotations

import json

from click.testing import CliRunner

from tools.cli.app import cli


class _Client:
    def create_direct_trial_plan(self, **payload):
        assert payload["run_spec_hash"] == "a" * 64
        assert payload["trial_role"] == "candidate"
        assert payload["comparison_id"] == "comparison-1"
        return {
            "binding_origin": "agent_direct",
            "trial_plan": payload["trial_plan"],
            "trial_plan_hash": "b" * 64,
            "trial_plan_ref": "trial-plan:sha256:" + "b" * 64,
            "trial_plan_version": 1,
            "trial_role": "candidate",
            "comparison_id": "comparison-1",
        }

    def get_direct_trial_plan(self, trial_plan_ref):
        return {
            "trial_plan_ref": trial_plan_ref,
            "trial_plan_hash": "b" * 64,
            "trial_plan": {"trial_plan_id": "direct-plan-1"},
        }


def test_agent_can_create_a_direct_trial_plan_binding(
    tmp_path, monkeypatch,
) -> None:
    source = tmp_path / "trial-plan.json"
    source.write_text(json.dumps({
        "schema_version": 1,
        "trial_plan_id": "direct-plan-1",
        "version": 1,
    }), encoding="utf-8")
    output = tmp_path / "trial-binding.json"
    monkeypatch.setattr(
        "tools.cli.commands.direct_trial.client_from_config",
        lambda: _Client(),
    )

    result = CliRunner().invoke(cli, [
        "trial-plan", "create",
        "--trial-plan-file", str(source),
        "--run-spec-hash", "a" * 64,
        "--trial-role", "candidate",
        "--comparison-id", "comparison-1",
        "--output", str(output),
        "--json",
    ])

    assert result.exit_code == 0, result.output
    binding = json.loads(output.read_text(encoding="utf-8"))
    assert binding["binding_origin"] == "agent_direct"
    assert binding["trial_plan_ref"] == "trial-plan:sha256:" + "b" * 64
    payload = json.loads(result.output)
    assert payload["output"] == str(output)
    report_action = payload["next_actions"][1]
    assert "--profile <profile>" in report_action["command"]
    assert "--report-workspace-id <id>" in report_action["command"]
    assert "--branch-id <branch>" in report_action["command"]
    assert "--report-parent-id <component>" in report_action["command"]
    assert "报告 ID" in report_action["description_zh"]
    assert "HEAD" in report_action["description_zh"]
    assert "--report-id" not in report_action["command"]


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
