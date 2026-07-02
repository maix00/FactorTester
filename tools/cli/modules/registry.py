"""Client-side controller adapters for server-registered modules.

The server registry is the only source of module metadata such as label, order,
kind and nesting.  The installed CLI only keeps local command adapters so a
server module key can open the matching client controller.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import click

from tools.cli.modules.backtest import add_group, backtest
from tools.cli.modules.custom_factors import custom_factors
from tools.cli.modules.products import products
from tools.cli.modules.single_factor_family_test import enter_single_factor_family_test, enter_single_factor_test


@dataclass(frozen=True, slots=True)
class ControllerAdapter:
    public_key: str
    backend_key: str
    commands: tuple[click.Command, ...]


class ControllerRegistry:
    def __init__(self) -> None:
        self._adapters = (
            ControllerAdapter(
                public_key="single_factor_test",
                backend_key="single_factor_test",
                commands=(enter_single_factor_test, enter_single_factor_family_test),
            ),
            ControllerAdapter(
                public_key="backtest",
                backend_key="group_test",
                commands=(backtest, add_group),
            ),
            ControllerAdapter(
                public_key="products",
                backend_key="products",
                commands=(products,),
            ),
            ControllerAdapter(
                public_key="custom_factors",
                backend_key="custom_factors",
                commands=(custom_factors,),
            ),
        )

    def commands(self) -> Iterable[click.Command]:
        for adapter in self._adapters:
            yield from adapter.commands

    def adapter_for_backend(self, key: str) -> ControllerAdapter | None:
        return next((adapter for adapter in self._adapters if adapter.backend_key == key), None)

    def adapter_for_public(self, key: str) -> ControllerAdapter | None:
        return next((adapter for adapter in self._adapters if adapter.public_key == key), None)


def register_cli_modules(cli: click.Group) -> None:
    for command in ControllerRegistry().commands():
        cli.add_command(command)
