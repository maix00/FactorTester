"""Client-side controller adapters for server-registered modules.

The server registry is the only source of module metadata such as label, order,
kind and nesting.  The installed CLI only keeps local command adapters so a
server module key can open the matching client controller.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import click

from tools.cli.modules.custom_factors import factor_library
from tools.cli.modules.products import product_library


@dataclass(frozen=True, slots=True)
class ControllerAdapter:
    public_key: str
    backend_key: str
    commands: tuple[click.Command, ...]


class ControllerRegistry:
    def __init__(self) -> None:
        self._adapters = (
            ControllerAdapter(
                public_key="product-library",
                backend_key="products",
                commands=(product_library,),
            ),
            ControllerAdapter(
                public_key="factor-library",
                backend_key="custom_factors",
                commands=(factor_library,),
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
