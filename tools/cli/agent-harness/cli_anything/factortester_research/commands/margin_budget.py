"""Thin CLI-Anything proxy for the real margin-budget CLI."""

from __future__ import annotations

import click

from ..utils.factortester_backend import run_factortester


@click.group("margin-budget")
def margin_budget() -> None:
    """Inspect or configure the real workspace margin budget."""


@margin_budget.command("show")
@click.option("--group", "group_id", default="")
@click.option("--json", "as_json", is_flag=True)
def show(group_id: str, as_json: bool) -> None:
    args = ["margin-budget", "show"]
    if group_id:
        args.extend(["--group", group_id])
    if as_json:
        args.append("--json")
    _delegate(args)


@margin_budget.command("configure")
@click.argument("group_id")
@click.option("--target", type=float)
@click.option("--max", "maximum", type=float)
@click.option("--tolerance", type=float)
@click.option("--json", "as_json", is_flag=True)
def configure(
    group_id: str,
    target: float | None,
    maximum: float | None,
    tolerance: float | None,
    as_json: bool,
) -> None:
    args = ["margin-budget", "configure", group_id]
    for option, value in (("--target", target), ("--max", maximum), ("--tolerance", tolerance)):
        if value is not None:
            args.extend([option, str(value)])
    if as_json:
        args.append("--json")
    _delegate(args)


def _delegate(args: list[str]) -> None:
    result = run_factortester(args)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "factortester command failed"
        raise click.ClickException(message)
    click.echo(result.stdout.rstrip())
