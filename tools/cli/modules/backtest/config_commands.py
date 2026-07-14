"""Backtest configuration command handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import click

from tools.cli.field_help import render_settings_help
from tools.cli.modules.backtest import config_args as config_arg_helpers
from tools.cli.modules.backtest import config_state as config_state_helpers
from tools.cli.modules.backtest import config_views as config_view_formatter


ArgValue = Callable[[tuple[str, ...], str], str]
StateAction = Callable[[Any], None]
ApplyRawSettings = Callable[[Any, tuple[str, ...]], None]
PrintLocalSettings = Callable[..., None]


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


def handle_local_settings_command(
    state,
    args: tuple[str, ...],
    *,
    apply_raw_settings: ApplyRawSettings,
    validate_registered_settings: StateAction,
    print_settings_help: StateAction,
    print_local_settings: PrintLocalSettings,
) -> bool:
    if not args or args[0] in {"show", "list", "ls"}:
        print_local_settings(state, validate_registered_settings=validate_registered_settings)
        return False
    show_help = config_arg_helpers.has_context_help(args)
    setting_args = config_arg_helpers.strip_context_help(args)
    if setting_args:
        apply_raw_settings(state, setting_args)
    if show_help:
        validate_registered_settings(state)
        print_settings_help(state)
        return False
    click.echo("已更新 local-settings")
    print_local_settings(state, validate=False, validate_registered_settings=validate_registered_settings)
    return True


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


def print_settings_help(state, *, values: dict[str, Any] | None = None) -> None:
    _, store = config_state_helpers.stores_for_backtest(state)
    for key, value in (values or {}).items():
        store.set(key, value)
    for line in render_settings_help(store, title="回测设置上下文"):
        click.echo(line)


def print_local_settings(
    state,
    *,
    validate: bool = True,
    validate_registered_settings: StateAction | None = None,
) -> None:
    if validate and validate_registered_settings is not None:
        validate_registered_settings(state)
    _, store = config_state_helpers.stores_for_backtest(state)
    for line in config_view_formatter.local_settings_lines(state.backtest_local_settings, store):
        click.echo(line)


def print_group_field_help(state, option: str, *, batch: bool = False) -> None:
    if option == "--add":
        print_group_add_help()
        return
    if option == "--batch":
        print_group_batch_help()
        return
    print_add_group_field_help(state, option)
    if batch:
        click.echo("  批量新增中 --group-index 由 --group-names 的顺序自动生成。")


def print_group_add_help() -> None:
    for line in config_view_formatter.GROUP_ADD_HELP_LINES:
        click.echo(line)


def print_group_batch_help() -> None:
    for line in config_view_formatter.GROUP_BATCH_HELP_LINES:
        click.echo(line)


def print_add_group_field_help(state, option: str) -> None:
    field_key = config_view_formatter.group_field_key_for_option(option)
    if field_key is None:
        raise click.ClickException(f"无法识别 group 字段: {option}")
    _, store = config_state_helpers.stores_for_backtest(state)
    lines = config_view_formatter.add_group_field_help_lines(option, field_key, store)
    if lines is None:
        raise click.ClickException(f"字段尚未由后端注册: {field_key}")
    for line in lines:
        click.echo(line)


def print_group_list(state) -> None:
    click.echo("分组列表")
    for line in config_view_formatter.group_list_lines(state.backtest_groups):
        click.echo(line)


def print_long_short_list(state) -> None:
    click.echo("Long-Short 列表")
    for line in config_view_formatter.long_short_list_lines(state.backtest_ls_configs):
        click.echo(line)


def print_group_detail(group: dict[str, Any]) -> None:
    for line in config_view_formatter.group_detail_lines(group):
        click.echo(line)


def print_result_hints() -> None:
    for line in config_view_formatter.RESULT_HINT_LINES:
        click.echo(line)


def print_run_strategy_info(groups: list[dict[str, Any]], ls_configs: list[dict[str, Any]]) -> None:
    for line in config_view_formatter.run_strategy_info_lines(groups, ls_configs):
        click.echo(line)


def print_run_topology(state, *, payload: dict[str, Any] | None, run_payload: dict[str, Any]) -> None:
    payload_strategy_book = run_payload.get("strategy_book")
    payload_ledger_configs = run_payload.get("ledger_configs")
    if state.backtest_strategy_book and payload is None:
        print_strategy_book(state)
    elif isinstance(payload_strategy_book, dict) and payload_strategy_book:
        print_strategy_book_payload(payload_strategy_book)
    if state.backtest_ledger_configs and payload is None:
        print_ledger_configs(state)
    elif isinstance(payload_ledger_configs, dict) and payload_ledger_configs:
        print_ledger_config_payload(payload_ledger_configs)
