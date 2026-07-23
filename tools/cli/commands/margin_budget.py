"""Inspect and configure workspace margin utilization budgets."""

from __future__ import annotations

import json

import click

from tools.cli.core.context import client_from_config
from tools.cli.core.errors import friendly_errors
from tools.cli.core.margin_budget import configure_margin_budget, margin_budget_rows
from tools.cli.state import load_state, save_state


@click.group("margin-budget")
def margin_budget() -> None:
    """Inspect target utilization, hard limit, and gross-leverage semantics."""


@margin_budget.command("show")
@click.option("--group", "group_id", default="")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def show_margin_budget(group_id: str, as_json: bool) -> None:
    state, configuration = _configuration()
    rows = margin_budget_rows(configuration["payload"])
    if group_id:
        rows = [row for row in rows if row["group_id"] == group_id]
        if not rows:
            raise click.ClickException(f"unknown strategy group: {group_id}")
    result = {"workspace_id": state.workspace_id, "revision": configuration["revision"], "strategies": rows}
    if as_json:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return
    for row in rows:
        click.echo(
            f"{row['group_id']} mode={row['margin_mode']} enabled={row['enabled']} "
            f"allocation={row['allocation_policy']} target={row['target_margin_utilization']:.4f} "
            f"max={row['max_margin_utilization']:.4f} tolerance={row['margin_utilization_tolerance']:.4f}"
        )


@margin_budget.command("configure")
@click.argument("group_id")
@click.option("--target", type=float)
@click.option("--max", "maximum", type=float)
@click.option("--tolerance", type=float)
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def configure_margin_budget_command(
    group_id: str,
    target: float | None,
    maximum: float | None,
    tolerance: float | None,
    as_json: bool,
) -> None:
    if target is None and maximum is None and tolerance is None:
        raise click.ClickException("至少提供 --target、--max 或 --tolerance")
    state, configuration = _configuration()
    try:
        payload, row = configure_margin_budget(
            configuration["payload"], group_id,
            target=target, maximum=maximum, tolerance=tolerance,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    updated = client_from_config().update_workspace_configuration(
        state.workspace_id, expected_revision=int(configuration["revision"]), payload=payload,
    )
    state.configuration_revision = int(updated["revision"])
    save_state(state)
    result = {"workspace_id": state.workspace_id, "revision": state.configuration_revision, "strategy": row}
    click.echo(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
        if as_json else f"{group_id} margin budget updated revision={state.configuration_revision}"
    )


def _configuration():
    state = load_state()
    if not state.workspace_id:
        raise click.ClickException("尚未选择 research workspace；请先运行 factortester workspace create/use")
    return state, client_from_config().get_workspace_configuration(state.workspace_id)
