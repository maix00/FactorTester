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
    """List home modules.

    Module-specific children are listed from that module command, for example:

      factortester single_factor_test list
      factortester backtest --help
    """
    modules = client_from_config().list_modules(parent=None)
    click.echo("当前位置: 首页")
    for line in module_lines(modules):
        click.echo(line)
    click.echo("查看模块下一层: factortester <module> list 或 factortester <module> --help")


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
