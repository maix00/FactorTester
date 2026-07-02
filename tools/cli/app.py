"""Click entrypoint for the separately installed FactorTester CLI."""

from __future__ import annotations

import click

from tools.cli.commands.auth import configure, login
from tools.cli.commands.navigation import back, home, list_modules
from tools.cli.commands.settings import describe, edit
from tools.cli.core.errors import backtest_errors as _backtest_errors
from tools.cli.modules.group_test import enter_group_test
from tools.cli.modules.single_factor_family_test import enter_single_factor_family_test


@click.group()
def cli() -> None:
    """FactorTester remote HTTP client."""


cli.add_command(configure)
cli.add_command(login)
cli.add_command(list_modules)
cli.add_command(home)
cli.add_command(back)
cli.add_command(describe)
cli.add_command(edit)
cli.add_command(enter_single_factor_family_test)
cli.add_command(enter_group_test)


if __name__ == "__main__":
    cli()
