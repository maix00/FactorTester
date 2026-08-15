"""Click entrypoint for the separate FactorTester Manager/operator CLI."""

from __future__ import annotations

import click

from tools.cli.commands.client_release import operator_client
from tools.cli.manager.commands import register_manager_commands
from tools.cli.manager.factortester_commands import (
    register_factor_tester_commands,
)


@click.group()
def manager_cli() -> None:
    """Authenticated FactorTester application Manager/operator commands."""


register_factor_tester_commands()
register_manager_commands(manager_cli)
manager_cli.add_command(operator_client)


if __name__ == "__main__":
    manager_cli()
