"""CLI-Anything proxy for the public FactorTester strategy commands."""

from __future__ import annotations

import click

from ..utils.factortester_backend import run_factortester


@click.group("strategy")
def strategy() -> None:
    """Inspect templates and validate a StrategySpec through FactorTester."""


@strategy.command("list")
@click.option("--workspace-root", type=click.Path(exists=True, file_okay=False))
@click.option("--json", "as_json", is_flag=True)
def list_strategies(workspace_root: str | None, as_json: bool) -> None:
    args = ["strategy", "list"]
    if workspace_root:
        args.extend(["--workspace-root", workspace_root])
    if as_json:
        args.append("--json")
    _delegate(args)


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


@strategy.group("actor")
def actor() -> None:
    """Inspect or scaffold a source-only Strategy Actor."""


@actor.command("inspect")
@click.argument("source", type=click.Path(exists=True, dir_okay=False))
@click.option("--json", "as_json", is_flag=True)
def inspect_actor(source: str, as_json: bool) -> None:
    args = ["strategy", "actor", "inspect", source]
    if as_json:
        args.append("--json")
    _delegate(args)


@actor.command("scaffold")
@click.argument("name")
@click.option("--output", required=True, type=click.Path(file_okay=False))
@click.option("--event", type=click.Choice(["bar", "market_feed"]), default="bar")
@click.option("--strategy-id", default=None)
@click.option("--workspace", type=click.Choice(["profile", "personal"]), default="profile")
@click.option("--json", "as_json", is_flag=True)
def scaffold_actor(name: str, output: str, event: str, strategy_id: str | None, workspace: str, as_json: bool) -> None:
    args = ["strategy", "actor", "scaffold", name, "--output", output, "--event", event]
    if strategy_id:
        args.extend(["--strategy-id", strategy_id])
    args.extend(["--workspace", workspace])
    if as_json:
        args.append("--json")
    _delegate(args)


def _delegate(args: list[str]) -> None:
    result = run_factortester(args)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "factortester command failed"
        raise click.ClickException(message)
    click.echo(result.stdout.rstrip())
