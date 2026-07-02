"""Generic navigation commands."""

from __future__ import annotations

import click

from tools.cli.core.context import client_from_config
from tools.cli.core.display import module_lines
from tools.cli.core.errors import friendly_errors


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
