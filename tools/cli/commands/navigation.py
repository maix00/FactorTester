"""Generic navigation commands."""

from __future__ import annotations

import click

from tools.cli.core.context import client_from_config
from tools.cli.core.display import module_lines, print_home_welcome
from tools.cli.core.errors import friendly_errors
from tools.cli.state import load_state, save_state


@click.command("list")
@friendly_errors
def list_modules() -> None:
    """List the next navigation layer from the current CLI location."""
    state = load_state()
    modules = client_from_config().list_modules(parent=state.current_parent)
    click.echo(f"当前位置: {state.location_label}")
    for line in module_lines(modules):
        click.echo(line)
    if state.current_parent is not None:
        click.echo("返回上一层: factortester back")


@click.command()
@friendly_errors
def home() -> None:
    """Return to the CLI home location."""
    state = load_state()
    state.reset()
    save_state(state)
    print_home_welcome()


@click.command()
@friendly_errors
def back() -> None:
    """Return to the previous navigation layer."""
    state = load_state()
    state.back()
    save_state(state)
    click.echo(f"已返回: {state.location_label}")

