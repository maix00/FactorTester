"""Client-side Module registry.

This registry manages CLI controller modules, using the same user-facing
"Module" concept as the frontend navigation layer. It intentionally does not
import the server-side ``tools.testers.registry.Module`` class: the installed
``factortester`` client can run on machines that do not have the server source
tree. The relation is by registered key/route contract, not Python class
identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import click

from tools.cli.modules.backtest import backtest
from tools.cli.modules.single_factor_family_test import enter_single_factor_family_test


@dataclass(frozen=True, slots=True)
class Module:
    key: str
    label: str
    order: int
    commands: tuple[click.Command, ...]


class ModuleRegistry:
    def __init__(self) -> None:
        self._modules = (
            Module(
                key="single_factor_family_test",
                label="单因子家族测试",
                order=10,
                commands=(enter_single_factor_family_test,),
            ),
            Module(
                key="backtest",
                label="回测",
                order=20,
                commands=(backtest,),
            ),
        )

    def sorted_modules(self) -> list[Module]:
        return sorted(self._modules, key=lambda module: module.order)

    def commands(self) -> Iterable[click.Command]:
        for module in self.sorted_modules():
            yield from module.commands


def register_cli_modules(cli: click.Group) -> None:
    for command in ModuleRegistry().commands():
        cli.add_command(command)
