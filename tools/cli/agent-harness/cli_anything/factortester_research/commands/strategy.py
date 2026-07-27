"""CLI-Anything proxy for the public FactorTester strategy commands."""

from __future__ import annotations

import click

from ..utils.factortester_backend import run_factortester


@click.group("strategy")
def strategy() -> None:
    """Inspect templates and validate a StrategySpec through FactorTester."""


@strategy.command("list")
@click.option("--json", "as_json", is_flag=True)
def list_strategies(as_json: bool) -> None:
    _delegate(["strategy", "list", *( ["--json"] if as_json else [] )])


@strategy.group("template")
def template() -> None:
    """Inspect built-in strategy templates."""


@template.command("list")
@click.option("--json", "as_json", is_flag=True)
def list_templates(as_json: bool) -> None:
    _delegate(["strategy", "template", "list", *( ["--json"] if as_json else [] )])


@template.command("show")
@click.argument("key")
@click.option("--json", "as_json", is_flag=True)
def show_template(key: str, as_json: bool) -> None:
    args = ["strategy", "template", "show", key]
    if as_json:
        args.append("--json")
    _delegate(args)


@strategy.command("validate")
@click.option("--spec", "spec_path", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--json", "as_json", is_flag=True)
def validate_strategy(spec_path: str, as_json: bool) -> None:
    args = ["strategy", "validate", "--spec", spec_path]
    if as_json:
        args.append("--json")
    _delegate(args)


def _delegate(args: list[str]) -> None:
    result = run_factortester(args)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "factortester command failed"
        raise click.ClickException(message)
    click.echo(result.stdout.rstrip())
