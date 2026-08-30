"""Thin research-Harness proxy for the real strategy intent CLI."""

from __future__ import annotations

import click

from ..utils.factortester_backend import run_factortester


@click.group("intent")
def strategy_intent() -> None:
    """Inspect or configure strategy intent through real FactorTester state."""


@strategy_intent.command("describe")
@click.option("--json", "as_json", is_flag=True)
def describe(as_json: bool) -> None:
    _delegate(["strategy", "intent", "describe", *(["--json"] if as_json else [])])


@strategy_intent.command("show")
@click.option("--group", "group_id", default="")
@click.option("--json", "as_json", is_flag=True)
def show(group_id: str, as_json: bool) -> None:
    args = ["strategy", "intent", "show"]
    if group_id:
        args.extend(["--group", group_id])
    if as_json:
        args.append("--json")
    _delegate(args)


@strategy_intent.command("configure")
@click.argument("group_id")
@click.option("--role", "roles", multiple=True)
@click.option("--clear-role", "clear_roles", multiple=True)
@click.option("--screen-rule", type=click.Choice(["disabled", "gte", "lte", "between"]))
@click.option("--screen-lower", type=float)
@click.option("--screen-upper", type=float)
@click.option("--allocation-policy", type=click.Choice(["equal_notional", "inverse_volatility", "equal_margin", "factor_sizing"]))
@click.option("--sizing-transform", type=click.Choice(["proportional", "inverse"]))
@click.option("--json", "as_json", is_flag=True)
def configure(
    group_id: str, roles: tuple[str, ...], clear_roles: tuple[str, ...],
    screen_rule: str | None, screen_lower: float | None, screen_upper: float | None,
    allocation_policy: str | None, sizing_transform: str | None, as_json: bool,
) -> None:
    args = ["strategy", "intent", "configure", group_id]
    for role in roles:
        args.extend(["--role", role])
    for role in clear_roles:
        args.extend(["--clear-role", role])
    for option, value in (
        ("--screen-rule", screen_rule), ("--screen-lower", screen_lower),
        ("--screen-upper", screen_upper), ("--allocation-policy", allocation_policy),
        ("--sizing-transform", sizing_transform),
    ):
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
