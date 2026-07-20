"""Shared CLI presentation helpers."""

from __future__ import annotations

from typing import Any

import click

from tools.cli.modules.keys import public_module_key


def module_lines(modules: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for module in modules:
        key = public_module_key(str(module.get("key", "")))
        label = module.get("label", key)
        kind = module.get("kind", "module")
        marker = " +" if module.get("has_children") else ""
        lines.append(f"- [{kind}] {key}: {label}{marker}")
    return lines


def print_home_welcome() -> None:
    click.echo("FactorTester CLI")
    click.echo("研究任务: factortester workspace --help / run --help / job --help")
    click.echo("数据管理: factortester products --help / custom_factors --help")
