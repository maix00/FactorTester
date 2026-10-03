"""Create an immutable TrialPlan binding for a direct experiment."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from tools.cli.core.context import client_from_config
from tools.cli.core.errors import friendly_errors


@click.group("trial-plan")
def trial_plan() -> None:
    """Validate and freeze direct research trial plans."""


@trial_plan.command("create")
@click.option(
    "--trial-plan-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--run-spec-hash", required=True)
@click.option("--trial-role", required=True)
@click.option("--comparison-id", required=True)
@click.option(
    "--output",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def create_direct_trial_plan(
    trial_plan_file: Path,
    run_spec_hash: str,
    trial_role: str,
    comparison_id: str,
    output: Path,
    as_json: bool,
) -> None:
    """Freeze one Agent-authored TrialPlan for a direct ResearchRun."""
    value = _read_object(trial_plan_file)
    binding = client_from_config().create_direct_trial_plan(
        trial_plan=value,
        run_spec_hash=run_spec_hash,
        trial_role=trial_role,
        comparison_id=comparison_id,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(binding, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    result = {
        "output": str(output),
        "binding_origin": str(binding.get("binding_origin") or ""),
        "trial_plan_ref": str(binding.get("trial_plan_ref") or ""),
        "trial_plan_hash": str(binding.get("trial_plan_hash") or ""),
        "next_actions": [{
            "command": (
                "factortester run submit --trial-binding-file "
                f"{output} --without-report --analysis <kind>"
            ),
            "description_zh": "提交不写研究报告的图外试验",
        }, {
            "command": (
                "factortester run submit --trial-binding-file "
                f"{output} --profile <profile> --report-workspace-id <id> "
                "--branch-id <branch> --report-parent-id <component> "
                "--analysis <kind>"
            ),
            "description_zh": (
                "提交时由 CLI 从当前报告 HEAD 冻结报告 ID 和父位置，"
                "并在终态后自动挂载结果"
            ),
        }],
    }
    if as_json:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return
    click.echo(f"trial_plan_ref={result['trial_plan_ref']}")
    click.echo(f"output={output}")


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise click.ClickException(f"invalid TrialPlan JSON: {path}") from exc
    if not isinstance(value, dict):
        raise click.ClickException("TrialPlan JSON must be an object")
    return value


@trial_plan.command("show")
@click.argument("trial_plan_ref")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def show_direct_trial_plan(trial_plan_ref: str, as_json: bool) -> None:
    """Read one content-addressed direct TrialPlan from the server."""
    value = client_from_config().get_direct_trial_plan(trial_plan_ref)
    if as_json:
        click.echo(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
        return
    click.echo(f"trial_plan_ref={value.get('trial_plan_ref')}")
    click.echo(f"trial_plan_id={value.get('trial_plan_id')}")
    click.echo(f"trial_plan_version={value.get('trial_plan_version')}")
