"""Click entrypoint for the separate FactorTester Manager/operator CLI."""

from __future__ import annotations

import click

from tools.cli.commands.admin import admin
from tools.cli.commands.agent_flow import operator_agent_flow
from tools.cli.commands.client_release import operator_client
from tools.cli.manager.commands import register_manager_commands


@click.group()
@click.option(
    "--port", "ports", multiple=True, type=click.IntRange(1, 65535),
    help="Admin 命令要查询的 FactorTester 端口；可重复指定。",
)
def manager_cli(ports: tuple[int, ...]) -> None:
    """FactorTester Manager and authorized operator commands.

    This executable is intentionally separate from the research CLI. Its
    authentication, server-control, agent-accounting, and release commands
    are not part of the ordinary research command surface.
    """


register_manager_commands(manager_cli)
manager_cli.add_command(admin)
manager_cli.add_command(operator_client)
manager_cli.add_command(operator_agent_flow)


if __name__ == "__main__":
    manager_cli()
