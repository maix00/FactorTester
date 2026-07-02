"""CLI module registry.

CLI modules are the user-facing controllers, not backend ExecutableModules.
Each module package owns its commands and registers them here through a small
descriptor so the root app stays generic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import click

from tools.cli.modules.backtest import backtest
from tools.cli.modules.single_factor_family_test import enter_single_factor_family_test


@dataclass(frozen=True, slots=True)
class CliModule:
    key: str
    label: str
    order: int
    commands: tuple[click.Command, ...]


class CliModuleRegistry:
    def __init__(self) -> None:
        self._modules = (
            CliModule(
                key="single_factor_family_test",
                label="单因子家族测试",
                order=10,
                commands=(enter_single_factor_family_test,),
            ),
            CliModule(
                key="backtest",
                label="回测",
                order=20,
                commands=(backtest,),
            ),
        )

    def sorted_modules(self) -> list[CliModule]:
        return sorted(self._modules, key=lambda module: module.order)

    def commands(self) -> Iterable[click.Command]:
        for module in self.sorted_modules():
            yield from module.commands


def register_cli_modules(cli: click.Group) -> None:
    for command in CliModuleRegistry().commands():
        cli.add_command(command)

