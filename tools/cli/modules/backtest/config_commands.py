"""Backtest configuration command handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import click

from tools.cli.modules.backtest import config_args as config_arg_helpers
from tools.cli.modules.backtest import config_state as config_state_helpers
from tools.cli.modules.backtest import config_views as config_view_formatter


ArgValue = Callable[[tuple[str, ...], str], str]


def handle_strategy_book_command(state, args: tuple[str, ...], *, arg_value: ArgValue) -> bool:
    if not args or args[0] in {"show", "list", "ls"}:
        print_strategy_book(state)
        return False
    if args[0] in {"help", "--help", "-h"}:
        print_strategy_book_help()
        return False
    if args[0] == "simple":
        state.backtest_strategy_book.clear()
        click.echo("已切换为 StrategyBookSimple: 每个 strategy 一个私有 ledger / cash pool")
        return True
    if args[0] == "ledger":
        config_state_helpers.apply_strategy_book_ledger(state, args[1:], arg_value=arg_value)
        print_strategy_book(state)
        return True
    if args[0] == "cash-pool":
        config_state_helpers.apply_strategy_book_cash_pool(state, args[1:], arg_value=arg_value)
        print_strategy_book(state)
        return True
    raise click.ClickException("strategy-book 支持: show, simple, ledger, cash-pool")


def handle_ledger_config_command(state, args: tuple[str, ...], *, arg_value: ArgValue) -> bool:
    if not args or args[0] in {"show", "list", "ls"}:
        print_ledger_configs(state)
        return False
    if args[0] in {"help", "--help", "-h"}:
        print_ledger_config_help()
        return False
    ledger = arg_value(args, "--ledger")
    if not ledger:
        raise click.ClickException("ledger-config 必须传 --ledger LEDGER")
    values = config_arg_helpers.parse_ledger_config_args(
        args,
        arg_value=arg_value,
        parse_raw_settings=config_arg_helpers.parse_raw_settings,
    )
    if not values:
        raise click.ClickException("ledger-config 缺少要设置的字段；用 --help 查看支持字段")
    current = dict(state.backtest_ledger_configs.get(ledger) or {})
    current.update(values)
    state.backtest_ledger_configs[ledger] = current
    click.echo(f"已更新 ledger config: {ledger}")
    print_ledger_configs(state)
    return True


def handle_clear_command(state, *, page_settings: bool) -> None:
    state.backtest_local_settings.clear()
    state.backtest_strategy_book.clear()
    state.backtest_ledger_configs.clear()
    state.backtest_groups.clear()
    state.backtest_ls_configs.clear()
    state.backtest_last_result.clear()
    if page_settings:
        state.page_settings.clear()
    click.echo("已清空 backtest 配置")
    if page_settings:
        click.echo("已同时清空页面级设置")


def print_strategy_book(state) -> None:
    print_strategy_book_payload(config_state_helpers.strategy_book_payload(state))


def print_strategy_book_payload(payload: dict[str, Any]) -> None:
    for line in config_view_formatter.strategy_book_lines(payload):
        click.echo(line)


def print_strategy_book_help() -> None:
    for line in config_view_formatter.STRATEGY_BOOK_HELP_LINES:
        click.echo(line)


def print_ledger_configs(state) -> None:
    click.echo("Ledger configs")
    print_ledger_config_payload(state.backtest_ledger_configs)


def print_ledger_config_payload(configs: dict[str, Any]) -> None:
    for line in config_view_formatter.ledger_config_lines(configs):
        click.echo(line)


def print_ledger_config_help() -> None:
    for line in config_view_formatter.LEDGER_CONFIG_HELP_LINES:
        click.echo(line)
