"""Shared CLI presentation helpers."""

from __future__ import annotations

from typing import Any

import click

from tools.cli.modules.keys import public_module_key
from tools.cli.state import CliState


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
    click.echo("欢迎使用 FactorTester CLI")
    click.echo("常用操作:")
    click.echo("  factortester list                         查看当前层级可进入模块")
    click.echo("  factortester single_factor_family_test    进入单因子家族测试")
    click.echo("  factortester back                         返回上一层")


def print_single_factor_family_welcome(state: CliState) -> None:
    click.echo("单因子家族测试")
    click.echo(f"已选择 factor_family: {state.factor_family}")
    click.echo("下一步: factortester list 查看测试模块；例如 factortester backtest 进入回测。")


def print_backtest_welcome(state: CliState) -> None:
    click.echo("回测")
    if state.factor_family:
        click.echo(f"因子家族: {state.factor_family}")
    click.echo("当前接口: group_test")
    click.echo("可用动作: factortester backtest add-group")
    click.echo("下一步: factortester list 查看回测设置 tabs；factortester back 返回。")


def print_location_welcome(state: CliState) -> None:
    if state.current_parent == "single_factor_family_test":
        print_single_factor_family_welcome(state)
        return
    if state.current_parent == "group_test":
        print_backtest_welcome(state)
        return
    click.echo(f"已进入: {state.location_label}")
    click.echo("下一步: factortester list 查看下一层；factortester back 返回。")
