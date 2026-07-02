"""Click entrypoint for the separately installed FactorTester CLI."""

from __future__ import annotations

import click

from tools.cli.commands.auth import configure, login
from tools.cli.commands.navigation import back, home, list_modules
from tools.cli.commands.settings import describe, edit
from tools.cli.core.errors import backtest_errors as _backtest_errors
from tools.cli.modules.registry import register_cli_modules


@click.group()
def cli() -> None:
    """FactorTester CLI.

    常用路径:

      factortester configure --host 127.0.0.1 --port 8114
      factortester login --username 18717974771
      factortester list
      factortester single_factor_test --factor-family SgCCS
      factortester backtest
      factortester backtest group --add --group-name A1 --split-count 5 --group-index 1 --factor-family SgCCS

    进入某个模块后再次运行 factortester list，只展示当前层级的下一层。
    字段级帮助示例:

      factortester group --add --group-name --help
      factortester group --add --group-name A1 --help
    """


cli.add_command(configure)
cli.add_command(login)
cli.add_command(list_modules)
cli.add_command(home)
cli.add_command(back)
cli.add_command(describe)
cli.add_command(edit)
register_cli_modules(cli)


if __name__ == "__main__":
    cli()
