"""Read historical TrialPlan records."""

from __future__ import annotations

import json

import click

from tools.cli.core.context import client_from_config
from tools.cli.core.errors import friendly_errors


@click.group("trial-plan")
def trial_plan() -> None:
    """Read historical TrialPlan references; new Runs declare sample_use."""


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
