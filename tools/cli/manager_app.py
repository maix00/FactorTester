"""Click entrypoint for the separate TradeResearch Manager/operator CLI."""

from __future__ import annotations

import click

from tools.cli.commands.client_release import operator_client
from tools.cli.manager.commands import register_manager_commands
from tools.cli.manager.traderesearch_commands import (
    register_traderesearch_commands,
)


@click.group()
def manager_cli() -> None:
    """Authenticated TradeResearch application Manager/operator commands."""


register_traderesearch_commands()
register_manager_commands(manager_cli)
manager_cli.add_command(operator_client)


if __name__ == "__main__":
    manager_cli()
